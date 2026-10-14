def average(numbers: list[float]) -> float:
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def greet(name: str) -> str:
    return f"Xin chào, {name}"


def total_length(words: list[str]) -> int:
    return sum(len(word) for word in words)
