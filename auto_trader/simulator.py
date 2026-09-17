def print_table(dan: int) -> None:
    """입력한 단의 구구단을 출력한다."""
    print(f"\n[{dan}단]")
    for number in range(1, 10):
        print(f"{dan} x {number} = {dan * number}")




def main() -> None:
    print("=== 구구단 전체 ===")
    for dan in range(2, 10):
        print_table(dan)

    while True:
        selected = input("\n보고 싶은 단을 입력하세요 (2~9, 종료: q): ").strip().lower()

        if selected == "q":
            print("프로그램을 종료합니다.")
            break

        if selected.isdigit() and 2 <= int(selected) <= 9:
            print_table(int(selected))
        else:
            print("2부터 9 사이의 숫자 또는 q를 입력하세요.")


if __name__ == "__main__":
    main()
