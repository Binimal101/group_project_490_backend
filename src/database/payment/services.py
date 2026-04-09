def luhn_sum(value: str) -> int:
    total = 0
    reverse_digits = value[::-1]

    for index, digit in enumerate(reverse_digits):
        number = int(digit)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number

    return total