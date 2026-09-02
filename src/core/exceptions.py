class FinancialPipelineError(Exception):
    """Base exception for all pipeline domain errors."""
    pass

class SQLQueryExecutionError(FinancialPipelineError):
    """Raised when database query execution fails."""
    pass

class EmptyPerformanceResultsError(FinancialPipelineError):
    """Raised when performance query yields no calculated metrics."""
    pass

class DataIngestionValidationError(FinancialPipelineError):
    """Raised when incoming raw CSV reports fail schema contracts or parsing rules."""
    pass