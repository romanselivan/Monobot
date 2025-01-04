import requests

# Ваш адрес
address = "UQC96lQ56uZUsvUlp6J7XE5vzao-QCM2tvigh43FDW_HYoxo"

# Публичный API для получения информации об аккаунте
url = f"https://toncenter.com/api/v2/getAddressInformation?address={address}"

# Отправка запроса
response = requests.get(url)

if response.status_code == 200:
    print(response.json())  # Выводим информацию о счете
else:
    print(f"Ошибка: {response.status_code}")