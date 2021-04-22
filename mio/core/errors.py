class MioError(Exception):
    def __str__(self) -> str:
        return repr(self)
