from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator
from typing import Annotated, Literal, Union, get_args, get_origin
from types import UnionType


def _has_integer(annotation):
    if hasattr(annotation, "__value__"):  # PEP 695 generated scalar alias
        return _has_integer(annotation.__value__)
    if get_origin(annotation) is Annotated:
        return _has_integer(get_args(annotation)[0])
    if get_origin(annotation) in (Union, UnionType):
        return any(_has_integer(item) for item in get_args(annotation))
    return annotation is int


class ContractModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, regex_engine="python-re")

    @field_validator("*", mode="before")
    @classmethod
    def json_integer(cls, value, info: ValidationInfo):
        annotation = cls.model_fields[info.field_name].annotation
        # JSON Schema integers include an integral JSON number (1.0). This also
        # applies to explicitly nullable integer fields, but never to booleans.
        if _has_integer(annotation) and type(value) is float and value.is_integer():
            return int(value)
        if get_origin(annotation) is Literal:
            kinds = {type(item) for item in get_args(annotation)}
            if (type(value) is bool and bool not in kinds) or (kinds == {bool} and type(value) is not bool):
                raise ValueError("JSON booleans and numeric constants are distinct")
        return value
