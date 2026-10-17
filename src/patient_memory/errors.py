class Problem(Exception):
    def __init__(self, status: int, code: str, message: str = "Request cannot be completed"):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)
