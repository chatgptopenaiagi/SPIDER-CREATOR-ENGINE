import sys

def celsius_to_fahrenheit(celsius: float) -> float:
    return celsius * 9/5 + 32

def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(1)
    try:
        celsius = float(sys.argv[1])
        fahrenheit = celsius_to_fahrenheit(celsius)
        print(f'{fahrenheit:.1f}')
    except ValueError:
        sys.exit(1)

if __name__ == '__main__':
    main()