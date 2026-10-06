from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def json_integer(cls, value, info: ValidationInfo):
        if cls.model_fields[info.field_name].annotation is int and type(value) is float and value.is_integer():
            return int(value)
        return value
