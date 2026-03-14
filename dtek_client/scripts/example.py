"""Script for manual testing of the DTEK API structure."""

import asyncio
import pprint

# Для тестування структури використовуємо заглушку
# from dtek_client.stub_client import StubDtekClient as DtekClient
# Коли захочемо перевірити реальний сервер (і отримали 403 Forbidden ), 
# міняємо імпорт на:
from dtek_client.client import DtekClient as DtekClient


async def main() -> None:
    print("--- Тестування високорівневих методів DTEK API ---")
    
    async with DtekClient("kem") as client:
        city = "м. Київ"
        street = "вул. Хрещатик"
        house = "10"
        
        print(f"\nШукаємо групу для: {city}, {street}, буд. {house}")
        try:
            # 1. Тестуємо пошук групи
            result = await client.get_group_by_address(city, street, house)
            print(f"Успіх! Знайдена група: {result.group_id}")
            
            # 2. Тестуємо розклад на сьогодні
            today_slots = await client.get_today_schedule(city, street, house)
            if today_slots:
                print(f"Розклад на сьогодні отримано (кількість слотів: {len(today_slots)})")
            else:
                print("Графік на сьогодні не застосовується (пусто).")
                
        except Exception as e:
            print(f"❌ Помилка: {e}")

if __name__ == "__main__":
    asyncio.run(main())