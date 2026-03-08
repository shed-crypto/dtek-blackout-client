"""Script for manual testing of the DTEK API structure."""

import asyncio
import pprint

# Для тестування структури використовуємо заглушку
# from dtek_client.stub_client import StubDtekClient as DtekClient
# Коли захочемо перевірити реальний сервер (і отримали 403 Forbidden ), 
# міняємо імпорт на:
from dtek_client.client import DtekClient as DtekClient


async def main() -> None:
    print("--- Тестування DTEK API ---")
    
    async with DtekClient("kem") as client:
        city_name = "м. Київ"
        test_street = "вул. Хрещатик"
        
        print(f"\n[1] Запит get_streets для '{city_name}':")
        streets = await client.get_streets(city_name)
        
        if streets:
            print(f"Успіх! Знайдено унікальних вулиць: {len(streets)}")
            print("Перші 5 вулиць (вивід через об'єкти):")
            for s in streets[:5]:
                print(f"  • {s.name}") # Звертаємося до атрибута .name
        else:
            print("Вулиць не знайдено.")

        print(f"\n[2] Запит get_home_num для '{test_street}':")
        try:
            home_num_raw = await client.get_home_num(city_name, test_street)
            
            if isinstance(home_num_raw, dict):
                print(f"Успіх! Отримано словник з ключами: {list(home_num_raw.keys())}")
                
                # У сирому JSON від ДТЕК будинки лежать у ключі "data", а не "houses"
                houses = home_num_raw.get("data", {})
                
                if houses and isinstance(houses, dict):
                    print(f"\nФрагмент списку будинків на {test_street}:")
                    for hn, data in list(houses.items())[:5]:
                        # Групи лежать у "group_ids"
                        groups = data.get("group_ids", []) if isinstance(data, dict) else "Невідомо"
                        print(f"  Будинок {hn:3} -> Групи відключень: {groups}")
                else:
                    print("Дані про будинки відсутні у ключі 'data'.")
            else:
                print("Помилка: отримано неочікуваний формат.")
        except Exception as e:
            print(f"Помилка під час запиту: {e}")

if __name__ == "__main__":
    asyncio.run(main())