from typing import Any, Dict, Sequence, Union

SourcePath = Union[str, Sequence[str]]
_Missing   = object()


class Sources:
    def __init__(self, **fields: SourcePath) -> None:
        self.fields = fields

    def fields_from_matrix(self, event: Dict[str, Any]) -> Dict[str, Any]:
        def retrieve(path: SourcePath) -> Any:
            data = event
            path = (path,) if isinstance(path, str) else path

            for part in path:
                data = data.get(part, _Missing)
                if data is _Missing:
                    break

            return data

        fields           = {k: retrieve(v) for k, v in self.fields.items()}
        fields["source"] = event
        return {k: v for k, v in fields.items() if v is not _Missing}
