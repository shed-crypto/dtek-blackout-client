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
            # Тепер тут повноцінний об'єкт HomeNumResponse
            response = await client.get_home_num(city_name, test_street)
            
            print(f"Успіх! Отримано об'єкт з {len(response.houses)} будинками.")
            print(f"Останнє оновлення бази ДТЕК: {response.update_timestamp}")

            if response.houses:
                print(f"\nФрагмент списку будинків на {test_street}:")
                # houses — це тепер словник об'єктів HouseEntry
                for hn, entry in list(response.houses.items())[:5]:
                    # Доступ через атрибути об'єкта
                    print(f"  Будинок {hn:3} -> Головна група: {entry.primary_group}")
            
            if response.preset:
                print(f"\nСтатус графіку: {'Активний' if response.preset.is_active else 'Неактивний'}")
                
        except Exception as e:
            print(f"Помилка валідації або запиту: {e}")

if __name__ == "__main__":
    asyncio.run(main())