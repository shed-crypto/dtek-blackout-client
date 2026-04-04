import asyncio
import logging
import datetime
import pprint
from curl_cffi.requests import AsyncSession
from dtek_client import DtekClient
from dtek_client.browser_auth import get_cleared_cookies
from dtek_client.models import SlotStatus

from dtek_client.stub_client import StubDtekClient

logging.basicConfig(level=logging.DEBUG)

def suggest_streets(all_streets: list, query: str) -> list[str]:
    """Фільтрує список вулиць по введеному запиту (без урахування регістру)."""
    q = query.lower().strip()
    return [s.name for s in all_streets if q in s.name.lower()]

def suggest_houses(all_houses: dict, query: str) -> list[str]:
    """Фільтрує список будинків по введеному префіксу."""
    q = query.lower().strip()
    # Сортуємо числово якщо можливо
    import re
    def sort_key(k: str) -> tuple:
        nums = re.findall(r'\d+', k)
        return (int(nums[0]) if nums else 9999, k)
    matched = [h for h in all_houses if q in h.lower()]
    return sorted(matched, key=sort_key)

async def create_session(base_url: str) -> AsyncSession:
    """Допоміжна функція для проходження WAF та налаштування сесії для конкретного сайту."""
    schedule_url = f"{base_url}/ua/shutdowns"
    cookies, csrf_token = await get_cleared_cookies(schedule_url)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "uk,en;q=0.9",
        "Origin": base_url,
        "Referer": schedule_url,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
        
    return AsyncSession(
        timeout=15.0, 
        headers=headers,
        cookies=cookies,
        impersonate="chrome120"
    )


async def test_stub() -> None:
    print("\n" + "="*50)
    print("=== ТЕСТ: Стаб-клієнт (StubDtekClient) ===")
    print("="*50)
    
    # Стаб-клієнт не потребує aiohttp/curl_cffi сесії чи реальних URL
    async with StubDtekClient("kem") as client:
        try:
            print("\n--- Вулиці м. Українка (Stub) ---")
            streets = await client.get_streets("м. Українка")
            for s in streets:
                print(f"  {s.name}")

            print("\n--- Будинки вул. Юності (Stub) ---")
            response = await client.get_home_num("м. Українка", "вул. Юності")
            
            # Сортуємо як числа, якщо це можливо, для гарного виводу
            def sort_key(k: str) -> float:
                import re
                nums = re.findall(r'\d+', k)
                return float(nums[0]) if nums else 0.0
                
            for house, entry in sorted(response.houses.items(), key=lambda x: sort_key(x[0])):
                status = "виключено з графіку" if entry.is_excluded else entry.primary_group
                print(f"  {house:6s} → {status}")

            print("\n--- Розклад на сьогодні (Факт) для будинку 1 (Stub) ---")
            slots = await client.get_today_schedule("м. Українка", "вул. Юності", "1")
            if slots and response.preset:
                # Виведемо перші 10 слотів, щоб не засмічувати консоль
                for key, status in list(slots.items())[:10]:
                    label = response.preset.time_zone.get(key, key)
                    icon = "⚡" if status.has_outage else ("~" if status.may_have_outage else "✓")
                    print(f"  {icon} {label:15s} {status.value}")
                print("  ... (далі ще слоти)")
            else:
                print("  Розклад на сьогодні ще не опублікований.")
                
            print("\n--- AddressResult: Прямий пошук групи (Stub) ---")
            address_result = await client.get_group_by_address("м. Українка", "вул. Юності", "1/1")
            print(f"  {address_result}")

        except Exception as e:
            print(f"Error in stub client: {e}")

async def test_krem() -> None:
    print("\n" + "="*50)
    print("=== ТЕСТ: Київські регіональні мережі (krem) ===")
    print("="*50)
    
    base_url = "https://www.dtek-krem.com.ua"
    try:
        session = await create_session(base_url)
        
        async with DtekClient("krem", ajax_url=f"{base_url}/ua/ajax", session=session) as client:
            try:
                print("\n--- Вулиці м. Українка ---")
                streets = await client.get_streets("м. Українка")
                for s in streets[:10]:
                    print(f"  {s.name}")

                print("\n--- Будинки вул. Юності ---")
                response = await client.get_home_num("м. Українка", "вул. Юності")
                for house, entry in sorted(response.houses.items()):
                    status = "виключено з графіку" if entry.is_excluded else entry.primary_group
                    print(f"  {house:6s} → {status}")

                print("\n--- Розклад на сьогодні (факт) ---")
                slots = await client.get_today_schedule("м. Українка", "вул. Юності", "10")
                if slots and response.preset:
                    for key, status in slots.items():
                        label = response.preset.time_zone.get(key, key)
                        icon = "⚡" if status.has_outage else ("~" if status.may_have_outage else "✓")
                        print(f"  {icon} {label:15s} {status.value}")
                else:
                    print("  Розклад на сьогодні ще не опублікований.")
                    
            except Exception as e:
                print(f"Error in krem: {e}")
    except Exception as e:
        print(f"Error in krem: {e}")

async def test_oem() -> None:
    print("\n" + "="*50)
    print("=== ТЕСТ: Одеські електромережі (oem) ===")
    print("="*50)
    
    base_url = "https://www.dtek-oem.com.ua"
    try:
        session = await create_session(base_url)
    
        async with DtekClient("oem", ajax_url=f"{base_url}/ua/ajax", session=session) as client:
            try:
                # --- Тест 1: Звичайний розклад для Одеси ---
                print("\n--- Розклад (м. Одеса, вул. Героїв оборони Одеси, 14) ---")
                response_odesa = await client.get_home_num("м. Одеса", "вул. Героїв оборони Одеси")
                
                # Шукаємо будинок
                house_num = "14"
                house_14 = response_odesa.houses.get(house_num)
                
                if not house_14:
                    print(f"  ❌ Будинок '{house_num}' не знайдено! Доступні номери: {list(response_odesa.houses.keys())[:15]}")
                elif house_14.is_excluded:
                    print("  🏠 Будинок виключено з графіку (немає групи).")
                else:
                    group_id = house_14.primary_group
                    print(f"  🏠 Група: {group_id}")
                    
                    # 1. ДИНАМІЧНИЙ РОЗКЛАД (ФАКТ)
                    print("\n  >> Динамічний розклад на сьогодні (Факт):")
                    slots = await client.get_today_schedule("м. Одеса", "вул. Героїв оборони Одеси", house_num)
                    if slots and response_odesa.preset:
                        for key, status in slots.items():
                            label = response_odesa.preset.time_zone.get(key, key)
                            icon = "⚡" if status.has_outage else ("~" if status.may_have_outage else "✓")
                            print(f"    {icon} {label:15s} {status.value}")
                    else:
                        print("    Розклад на сьогодні ще не опублікований.")

                    # 2. СТАТИЧНИЙ РОЗКЛАД (ПРЕСЕТ)
                    print("\n  >> Статичний розклад на тиждень (Пресет):")
                    if response_odesa.preset:
                        week_schedule = response_odesa.preset.groups.get(group_id)
                        if week_schedule:
                            # Спочатку виведемо заголовок (годинні слоти 00, 01, 02...)
                            header = [response_odesa.preset.time_zone.get(str(i), str(i))[:2] for i in range(1, 25)]
                            print(f"    {'День':10s} | {' '.join(header)}")
                            print(f"    {'-'*11}+{'-'*71}")
                            
                            for day_idx in range(1, 8):
                                day_name = response_odesa.preset.days.get(day_idx, f"День {day_idx}")
                                day_data = week_schedule.get_day(day_idx)
                                if day_data:
                                    visual_slots = []
                                    for tz_key, status in day_data.slots.items():
                                        if status == SlotStatus.NO:
                                            visual_slots.append("⚡ ")  # Точно немає цілу годину
                                        elif status == SlotStatus.MAYBE:
                                            visual_slots.append("~ ")  # Можливо немає цілу годину
                                        elif status == SlotStatus.FIRST:
                                            visual_slots.append("⚡½")  # Немає перші 30 хв (напр. 09:00-09:30)
                                        elif status == SlotStatus.SECOND:
                                            visual_slots.append("½⚡")  # Немає другі 30 хв (напр. 09:30-10:00)
                                        elif status == SlotStatus.MFIRST:
                                            visual_slots.append("~½")  # Можливо немає перші 30 хв
                                        elif status == SlotStatus.MSECOND:
                                            visual_slots.append("½~")  # Можливо немає другі 30 хв
                                        elif status == SlotStatus.YES:
                                            visual_slots.append("✓ ")  # Точно є світло
                                        else:
                                            visual_slots.append("❓ ")
                                            
                                    print(f"    {day_name:10s} | {' '.join(visual_slots)}")
                        else:
                            print(f"    ❌ Не знайдено статичного графіка для черги {group_id}")
                    else:
                        print("    ❌ ДТЕК не повернув статичний графік (preset) для цієї адреси.")

                # --- Тест 2: Складна схема підключення ---
                print("\n--- Складна схема підключення (с. Шевченкове) ---")
                response_shevchenkove = await client.get_home_num("с. Шевченкове", "вул. Шевченка Т.")
                house_1 = response_shevchenkove.houses.get("1")
                
                if house_1:
                    if house_1.is_multi_group:
                        print("  ⚠️ УВАГА: За цією адресою будинок має складну схему підключення.")
                        print(f"  Він належить до кількох груп одночасно: {house_1.group_ids}")
                        print("  Точний прогноз неможливий.")
                    elif house_1.is_excluded:
                        print("  Будинок виключено з графіків відключень.")
                    else:
                        print(f"  Звичайний будинок. Група: {house_1.primary_group}")
                else:
                    print("  Будинок 1 не знайдено.")

            except Exception as e:
                print(f"Error in oem: {e}")
    except Exception as e:
        print(f"Error in krem: {e}")

async def test_kem() -> None:
    print("\n" + "="*50)
    print("=== ТЕСТ: Київські електромережі (kem) ===")
    print("="*50)
    
    base_url = "https://www.dtek-kem.com.ua"
    try:
        session = await create_session(base_url)
        
        async with DtekClient("kem", ajax_url=f"{base_url}/ua/ajax", session=session) as client:
            try:
                print("\n--- Вулиці м. Київ (перші 10) ---")
                streets = await client.get_streets("м. Київ")
                for s in streets[:10]:
                    print(f"  {s.name}")

                test_street = "вул. Хрещатик"
                print(f"\n--- Будинки: {test_street} ---")
                response = await client.get_home_num("м. Київ", test_street)
                
                # Сортуємо для гарного виводу
                import re
                def sort_key(k: str) -> tuple:
                    nums = re.findall(r'\d+', k)
                    return (int(nums[0]) if nums else 9999, k)
                    
                # Виведемо перші 15 будинків
                for house in sorted(response.houses.keys(), key=sort_key)[:15]:
                    entry = response.houses[house]
                    status = "виключено з графіку" if entry.is_excluded else entry.primary_group
                    print(f"  {house:6s} → {status}")

                test_house = "1"
                print(f"\n--- Розклад на сьогодні (факт) для {test_street}, {test_house} ---")
                
                if test_house in response.houses:
                    slots = await client.get_today_schedule("м. Київ", test_street, test_house)
                    if slots and response.preset:
                        for key, status in slots.items():
                            label = response.preset.time_zone.get(key, key)
                            icon = "⚡" if status.has_outage else ("~" if status.may_have_outage else "✓")
                            print(f"  {icon} {label:15s} {status.value}")
                    else:
                        print("  Розклад на сьогодні ще не опублікований.")
                else:
                    print(f"  ❌ Будинок '{test_house}' не знайдено!")
                    
            except Exception as e:
                print(f"Error in kem: {e}")
    except Exception as e:
        print(f"Error in kem session creation: {e}")

async def test_autocomplete_stub() -> None:
    """Демонстрація автодоповнення вулиць та номерів будинків через StubDtekClient."""
    print("\n" + "=" * 55)
    print("=== ТЕСТ: Автодоповнення адреси (Stub) ===")
    print("=" * 55)
 
    city = "м. Українка"
 
    async with StubDtekClient("kem") as client:
 
        # ── Крок 1: Автодоповнення вулиці ────────────────────────────────────
        #
        # Алгоритм:
        #   1. Завантажуємо ВСІ вулиці міста одним запитом (get_streets).
        #   2. Фільтруємо локально по тому що ввів користувач.
        #   3. Можна кешувати результат get_streets — він не змінюється часто.
        #
        print(f"\n📍 Місто: {city}")
        all_streets = await client.get_streets(city)
 
        # Симулюємо різні варіанти введення
        street_queries = ["юн", "сад", "пар", "незал", "вул"]
        for user_input in street_queries:
            suggestions = suggest_streets(all_streets, user_input)
            print(f"\n  Ввід: «{user_input}»  →  {len(suggestions)} підказок:")
            for s in suggestions:
                print(f"    • {s}")
 
        # ── Крок 2: Вибір вулиці та автодоповнення номера будинку ────────────
        #
        # Алгоритм:
        #   1. Після вибору вулиці викликаємо get_home_num(city, street).
        #   2. response.houses — це dict {номер: HouseEntry}.
        #   3. Фільтруємо ключі по введеному номеру.
        #
        chosen_street = "вул. Юності"
        print(f"\n\n🏠 Вулиця обрана: {chosen_street}")
        response = await client.get_home_num(city, chosen_street)
        all_house_numbers = response.houses  # dict[str, HouseEntry]
 
        house_queries = ["1", "2", ""]  # "" → показати всі
        for user_input in house_queries:
            suggestions = suggest_houses(all_house_numbers, user_input)
            label = f"«{user_input}»" if user_input else "(порожньо — всі)"
            print(f"\n  Ввід: {label}  →  {len(suggestions)} підказок:")
            for h in suggestions:
                entry = all_house_numbers[h]
                group = "виключено з графіку" if entry.is_excluded else entry.primary_group
                print(f"    • {h:6s}  →  {group}")
 
        # ── Крок 3: Повний результат після вибору конкретного будинку ─────────
        print("\n\n✅ Повний результат (вул. Юності, буд. 1/1):")
        result = await client.get_group_by_address(city, chosen_street, "1/1")
        print(f"  {result}")

async def test_autocomplete_real() -> None:
    """Демонстрація автодоповнення з реальним підключенням до dtek-krem.com.ua."""
    print("\n" + "=" * 60)
    print("=== ТЕСТ: Автодоповнення адреси (реальне підключення) ===")
    print("=" * 60)
 
    base_url = "https://www.dtek-krem.com.ua"
    city = "м. Українка"
 
    # ── Крок 0: Підключення ───────────────────────────────────────────────────
    print(f"\n⏳ Підключення до {base_url} (обхід WAF)...")
    try:
        session = await create_session(base_url)
    except Exception as e:
        print(f"  ❌ Не вдалося підключитися: {e}")
        return
 
    async with DtekClient(
        "krem",
        ajax_url=f"{base_url}/ua/ajax",
        session=session,
    ) as client:
 
        # ── Крок 1: Завантажуємо всі вулиці міста ────────────────────────────
        # Один мережевий запит → кешуємо результат.
        print(f"\n📡 Завантаження вулиць для «{city}»...")
        try:
            all_streets = await client.get_streets(city)
        except Exception as e:
            print(f"  ❌ Помилка: {e}")
            return
 
        print(f"  ✅ Отримано {len(all_streets)} вулиць.")
 
        # ── Крок 2: Симулюємо введення вулиці ────────────────────────────────
        print("\n── Автодоповнення вулиці ──────────────────────────────────────")
        street_queries = ["юн", "сад", "пар", "цент", "ш"]
        for user_input in street_queries:
            suggestions = suggest_streets(all_streets, user_input)
            count = len(suggestions)
            print(f"\n  Ввід: «{user_input}»  →  {count} підказок:")
            # Показуємо не більше 5 щоб не засмічувати вивід
            for s in suggestions[:5]:
                print(f"    • {s}")
            if count > 5:
                print(f"    … ще {count - 5}")
 
        # ── Крок 3: Обираємо вулицю, завантажуємо будинки ────────────────────
        # Один мережевий запит → кешуємо response для подальшої фільтрації.
        chosen_street = suggest_streets(all_streets, "юності")
        if not chosen_street:
            # Якщо «вул. Юності» немає — беремо першу доступну
            chosen_street = [all_streets[0].name] if all_streets else []
 
        if not chosen_street:
            print("\n  ❌ Не знайдено жодної вулиці для прикладу.")
            return
 
        street = chosen_street[0]
        print(f"\n\n📡 Вулиця обрана: «{street}» — завантаження будинків...")
        try:
            response = await client.get_home_num(city, street)
        except Exception as e:
            print(f"  ❌ Помилка: {e}")
            return
 
        all_houses = response.houses  # dict[str, HouseEntry]
        print(f"  ✅ Отримано {len(all_houses)} будинків.")
 
        # ── Крок 4: Симулюємо введення номера будинку ─────────────────────────
        print("\n── Автодоповнення номера будинку ──────────────────────────────")
        house_queries = ["1", "2", "10", ""]   # "" → показати перші 10 (всі)
        for user_input in house_queries:
            if user_input == "":
                # Порожній ввід — показуємо перші 10 будинків
                import re as _re
 
                def _sort_key(k: str) -> tuple:
                    nums = _re.findall(r"\d+", k)
                    return (int(nums[0]) if nums else 9999, k)
 
                all_sorted = sorted(all_houses.keys(), key=_sort_key)
                suggestions_h = all_sorted[:10]
                label = "(порожньо — перші 10)"
            else:
                suggestions_h = suggest_houses(all_houses, user_input)
                label = f"«{user_input}»"
 
            print(f"\n  Ввід: {label}  →  {len(suggestions_h)} підказок:")
            for h in suggestions_h:
                entry = all_houses[h]
                group = (
                    "виключено з графіку"
                    if entry.is_excluded
                    else (entry.primary_group or "невідомо")
                )
                print(f"    • {h:8s}  →  {group}")
 
        # ── Крок 5: Повний результат після вибору конкретного будинку ─────────
        # Беремо перший знайдений будинок як приклад.
        example_house = suggest_houses(all_houses, "1")
        if example_house:
            chosen_house = example_house[0]
            print(f"\n\n✅ Повний результат ({city}, {street}, буд. {chosen_house}):")
            result = await client.get_group_by_address(city, street, chosen_house)
            print(f"  Група:    {result.group_id}")
            print(f"  Назва:    {result.group_display_name}")
            print(f"  Адреса:   {result.city}, {result.street}, {result.house_number}")

async def test_fact_real() -> None:
    print("\n" + "="*50)
    print("--- Тестування DTEK API (Київ) ---")
    print("="*50)
    
    base_url = "https://www.dtek-kem.com.ua"
    
    try:
        # 1. Створюємо сесію з проходженням WAF (як у test_krem)
        session = await create_session(base_url)
        
        # 2. Передаємо сесію та ЯВНО вказуємо ajax_url
        async with DtekClient(
            "kem", 
            ajax_url=f"{base_url}/ua/ajax", 
            session=session
        ) as client:
            
            city_name = "м. Київ"
            test_street = "вул. Хрещатик"
            test_house = "1"

            print(f"\n[1] Запит get_streets для '{city_name}':")
            streets = await client.get_streets(city_name)
 
            if streets:
                print(f"Успіх! Знайдено унікальних вулиць: {len(streets)}")
                print("Перші 5 вулиць (вивід через об'єкти):")
                for s in streets[:5]:
                    print(f"  • {s.name}")
            else:
                print("Вулиць не знайдено.")
    
            print(f"\n[2] Запит get_home_num для '{test_street}':")
            try:
                response = await client.get_home_num(city_name, test_street)
    
                print(f"Успіх! Отримано об'єкт з {len(response.houses)} будинками.")
                print(f"Останнє оновлення бази ДТЕК: {response.update_timestamp}")
    
                if response.houses:
                    print(f"\nФрагмент списку будинків на {test_street}:")
                    for hn, entry in list(response.houses.items())[:5]:
                        print(f"  Будинок {hn:3} -> Головна група: {entry.primary_group}")
    
                if response.preset:
                    print(f"\nСтатус графіку: {'Активний' if response.preset.is_active else 'Неактивний'}")
    
            except Exception as e:
                print(f"Помилка валідації або запиту: {e}")
                return
    
            # ── [3] Нові методи дат ───────────────────────────────────────────────
    
            print(f"\n[3] Нові методи дат для '{test_street}', буд. {test_house}:")
    
            # 3а. Доступні дати факту (для UI-вкладок «сьогодні / завтра»)
            dates = client.get_available_fact_dates(response)
            if dates:
                today = datetime.date.fromtimestamp(response.fact.today_ts)
                print(f"  Доступні дати факту ({len(dates)} шт.):")
                for d in dates:
                    label = ""
                    if d == today:
                        label = " ← сьогодні"
                    elif d == today + datetime.timedelta(days=1):
                        label = " ← завтра"
                    print(f"    {d}{label}")
            else:
                print("  Дат факту не знайдено (fact відсутній або порожній).")
    
            # 3б. Графік на завтра
            print(f"\n  get_tomorrow_schedule:")
            try:
                tmrw = await client.get_tomorrow_schedule(city_name, test_street, test_house)
                if tmrw is None:
                    print("  → Завтрашній графік ще не опублікований (None).")
                else:
                    outages = sum(1 for v in tmrw.values() if v.has_outage)
                    print(f"  → Є дані: {len(tmrw)} слотів, з них відключень: {outages}")
                    
                    # ДОДАНО: Виведення повного графіка на завтра
                    for key, status in tmrw.items():
                        label = response.preset.time_zone.get(key, key) if response.preset else key
                        icon = "⚡" if status.has_outage else ("~" if status.may_have_outage else "✓")
                        print(f"      {icon} {label:15s} {status.value}")

            except Exception as e:
                print(f"  → Помилка: {e}")
    
            # 3в. Графік для конкретної дати (перебираємо всі доступні)
            print(f"\n  get_schedule_for_date (по всіх доступних датах):")
            for d in dates:
                try:
                    slots = await client.get_schedule_for_date(
                        city_name, test_street, test_house, d
                    )
                    if slots is None:
                        print(f"    {d}: немає даних")
                    else:
                        outages = sum(1 for v in slots.values() if v.has_outage)
                        print(f"    {d}: {len(slots)} слотів, відключень: {outages}")
                        
                        # ДОДАНО: Виведення повного графіка для кожної дати
                        for key, status in slots.items():
                            label = response.preset.time_zone.get(key, key) if response.preset else key
                            icon = "⚡" if status.has_outage else ("~" if status.may_have_outage else "✓")
                            print(f"      {icon} {label:15s} {status.value}")

                except Exception as e:
                    print(f"    {d}: помилка — {e}")
                    
    # ЗМІНЕНО: Глобальний except більше не використовує локальну змінну d
    except Exception as e:
        print(f"Глобальна помилка у test_fact_real: {e}")

async def main() -> None:
    #await test_stub()   # Спочатку тестуємо стаб (швидко, без мережі)
    #await test_krem()   # Тестуємо Київську область
    #await test_oem()    # Тестуємо Одесу
    #await test_kem()    # Тестуємо Київ (місто)
    #await test_autocomplete_stub() # Тестуємо автозавершення локально
    #await test_autocomplete_real() # Тестуємо автозавершення онлайн
    await test_fact_real() # Тестуємо фактичний графік онлайн
if __name__ == "__main__":
    asyncio.run(main())