from .base_service import BaseGeoAIService


class ExperimentalService(BaseGeoAIService):
    def run_python_code(self, code, result_var="result"):
        return self.execute_python_code(code=code, result_var=result_var)
