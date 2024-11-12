import argparse
import subprocess
import os

def main():
    # Создаем парсер аргументов
    parser = argparse.ArgumentParser(description='Convert images to analog video signal simulation using colormodem.py.')
    parser.add_argument('input_image', type=str, help='Path to the input image file.')
    parser.add_argument('output_image', type=str, help='Path to save the output image file.')

    # Парсим аргументы
    args = parser.parse_args()

    # Проверяем существование входного файла
    if not os.path.isfile(args.input_image):
        print(f"Error: The input file '{args.input_image}' does not exist.")
        return

    # Вызываем colormodem.py с subprocess
    try:
        subprocess.run(['python', 'colormodem.py', args.input_image, args.output_image], check=True)
        print(f"Image processed successfully! Output saved as '{args.output_image}'.")
    except subprocess.CalledProcessError as e:
        print(f"Error during processing: {e}")

if __name__ == '__main__':
    main()