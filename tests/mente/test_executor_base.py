from mente.executors.base import Executor


def test_executor_subclass_contract():
    class _FakeExecutor(Executor):
        def execute(self, request):
            return None

    executor = _FakeExecutor()
    assert executor is not None
