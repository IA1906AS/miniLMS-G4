from my_project.calculator import average, greet, total_length


def test_average() -> None:
    assert average([2.0, 4.0, 6.0]) == 4.0


def test_average_empty() -> None:
    assert average([]) == 0.0


def test_greet() -> None:
    assert greet("An") == "Xin chào, An"


def test_total_length() -> None:
    assert total_length(["abc", "de"]) == 5
