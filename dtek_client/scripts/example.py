"""Script for manual testing of the DTEK API structure."""

import asyncio
import pprint

# Для тестування структури використовуємо заглушку
# from dtek_client.stub_client import StubDtekClient as DtekClient
# Коли захочемо перевірити реальний сервер (і отримали 403 Forbidden ), 
# міняємо імпорт на:
from dtek_client.client import DtekClient as DtekClient


async def main() -> None:
    print("--- Тестування DTEK API (Повертаємо сирі словники) ---")
    
    # Ініціалізуємо клієнта для Київської області
    async with DtekClient("kem") as client:
        
        # 1. Тестуємо отримання вулиць
        print("\n[1] Запит get_streets для 'м. Українка':")
        streets_raw = await client.get_streets("м. Українка")
        
        if isinstance(streets_raw, list):
            print(f"Знайдено вулиць: {len(streets_raw)}")
            pprint.pprint(streets_raw[:3])
        else:
            print("Отримано неочікуваний формат:", streets_raw)

        # 2. Тестуємо отримання номерів будинків та графіка
        print("\n[2] Запит get_home_num для 'вул. Юності':")
        home_num_raw = await client.get_home_num("м. Українка", "вул. Юності")
        
        # Оскільки JSON великий, ми просто дивимося на його ключі
        if isinstance(home_num_raw, dict):
            print(f"Успіх! Отримано словник з такими ключами: {list(home_num_raw.keys())}")
            
            # Виведемо шматочок даних, щоб побачити структуру будинків
            print("\nФрагмент списку будинків:")
            houses = home_num_raw.get("houses", {})
            # Виводимо тільки перші 2 будинки
            for hn, data in list(houses.items())[:2]:
                print(f"Будинок {hn}: {data}")
        else:
            print("Помилка: отримано не словник.")

if __name__ == "__main__":
    asyncio.run(main())