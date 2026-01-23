class ToolError(RuntimeError):
    pass


class TransientToolError(ToolError):
    pass


class DeterministicToolError(ToolError):
    pass

