import "@typespec/http";
import "@typespec/openapi3";
import "@typespec/json-schema";
import "./backend.tsp";

using TypeSpec.JsonSchema;
@service(#{ title: "vgpu public backend protocol (experimental)" })
@jsonSchema
namespace Vgpu.V1;
