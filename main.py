import logging
import threading
from sqlalchemy import create_engine
from config import DB_CONFIG, API_ID, API_HASH, BOT_TOKEN, CHAT_ID
from models import Base, User, Session as SessionModel
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from sqlalchemy.orm import sessionmaker
import hashlib
import asyncio
from telethon import TelegramClient
import getpass
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# Настройка логирования (вывод в файл)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filename='bot.log')
logger = logging.getLogger(__name__)

# Подключение к базе данных
engine = create_engine(
    f"postgresql+psycopg2://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# Инициализация Telegram-клиента
client = TelegramClient("bot", API_ID, API_HASH)

# Асинхронная функция для запуска клиента
async def start_telegram_client():
    """Запускает Telegram-клиент с использованием bot_token."""
    await client.start(bot_token=BOT_TOKEN)
    logger.info("Telegram-клиент успешно аутентифицирован")

# Асинхронная функция для завершения работы клиента
async def stop_telegram_client():
    """Завершает работу Telegram-клиента."""
    await client.disconnect()
    logger.info("Telegram-клиент отключен")

# Асинхронная функция для отправки уведомлений
async def send_notification(message):
    """Отправляет уведомление в Telegram."""
    try:
        await client.send_message(CHAT_ID, message, parse_mode='md')
        logger.info(f"Уведомление отправлено: {message}")
    except Exception as e:
        logger.exception(f"Ошибка при отправке уведомления: {e}")

# Функция извлечения ошибок с формы
def get_form_errors(driver):
    """Извлекает ошибки из формы на сайте."""
    errors = []
    try:
        error_lists = driver.find_elements(By.CLASS_NAME, "errorlist")
        for error_list in error_lists:
            errors.extend([item.text for item in error_list.find_elements(By.TAG_NAME, "li")])
        nonfield_errors = driver.find_elements(By.CLASS_NAME, "errorlist.nonfield")
        for nonfield_error in nonfield_errors:
            errors.extend([item.text for item in nonfield_error.find_elements(By.TAG_NAME, "li")])
    except Exception as e:
        logger.error(f"Ошибка при извлечении ошибок: {e}")
    return errors

# Регистрация пользователя
def register_user():
    """Регистрирует пользователя на сайте и сохраняет данные в базе."""
    chrome_options = Options()
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--silent")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    try:
        driver.get("https://cappa.csu.ru/auth/signup/")
        logger.info("Открыта страница регистрации")

        username = input("Введите имя пользователя: ").strip()
        email = input("Введите почту: ").strip()
        first_name = input("Введите ваше имя: ").strip()
        last_name = input("Введите вашу фамилию: ").strip()
        password = getpass.getpass("Введите пароль: ")
        password_repeat = getpass.getpass("Повторите пароль: ")

        if not all([username, email, first_name, last_name, password, password_repeat]):
            logger.error("Все поля должны быть заполнены")
            print("Ошибка: все поля должны быть заполнены.")
            return None, None, None
        if password != password_repeat:
            logger.error("Пароли не совпадают")
            print("Ошибка: пароли не совпадают.")
            return None, None, None

        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.ID, "id_username"))).send_keys(username)
        driver.find_element(By.ID, "id_email").send_keys(email)
        driver.find_element(By.ID, "id_first_name").send_keys(first_name)
        driver.find_element(By.ID, "id_last_name").send_keys(last_name)
        driver.find_element(By.ID, "id_password1").send_keys(password)
        driver.find_element(By.ID, "id_password2").send_keys(password_repeat)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']"))).click()

        try:
            wait.until(EC.url_changes("https://cappa.csu.ru/auth/signup/"))
            if "signup" in driver.current_url:
                errors = get_form_errors(driver)
                logger.error("Ошибки при регистрации: " + ", ".join(errors))
                print("Ошибки при регистрации:", ", ".join(errors))
                return None, None, None
        except TimeoutException:
            errors = get_form_errors(driver)
            if errors:
                logger.error("Ошибки при регистрации: " + ", ".join(errors))
                print("Ошибки при регистрации:", ", ".join(errors))
                return None, None, None

        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        with Session() as session:
            new_user = User(username=username, password=hashed_password)
            session.add(new_user)
            session.commit()
            user_id = new_user.id
            logger.info(f"Пользователь {username} зарегистрирован с ID {user_id}")

        message = f"❗ Новый пользователь зарегистрирован: `{username}` (ID: {user_id})"
        asyncio.run_coroutine_threadsafe(send_notification(message), client.loop)
        return username, user_id, driver
    except TimeoutException:
        logger.error("Превышено время ожидания при регистрации")
        print("Ошибка: превышено время ожидания.")
        return None, None, None
    except NoSuchElementException:
        logger.error("Элемент не найден на странице регистрации")
        print("Ошибка: элемент не найден на странице.")
        return None, None, None
    except Exception as e:
        logger.error(f"Ошибка при регистрации: {e}")
        print(f"Ошибка при регистрации: {e}")
        return None, None, None
    finally:
        pass  # Оставляем driver открытым для дальнейших действий

# Авторизация пользователя
def authorize_user():
    """Авторизует пользователя на сайте и записывает сеанс в базу."""
    chrome_options = Options()
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--silent")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    try:
        driver.get("https://cappa.csu.ru/auth/signin/")
        logger.info("Открыта страница авторизации")

        with Session() as session:
            users = [user for user in session.query(User).all() if user.username]
            if not users:
                logger.error("Нет зарегистрированных пользователей в базе")
                print("Ошибка: нет зарегистрированных пользователей.")
                return False, None, None
            print("Доступные пользователи:")
            for i, user in enumerate(users, 1):
                print(f"{i}. {user.username}")
            try:
                choice = int(input("Выберите пользователя (введите номер): ")) - 1
                if choice < 0 or choice >= len(users):
                    raise ValueError
            except ValueError:
                logger.error("Неверный выбор пользователя")
                print("Ошибка: неверный выбор пользователя.")
                return False, None, None
            username = users[choice].username

        password = getpass.getpass(f"Введите пароль для {username}: ")
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.ID, "id_login"))).send_keys(username)
        driver.find_element(By.ID, "id_password").send_keys(password)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']"))).click()

        try:
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "profile__bar-username")))
            logger.info(f"Пользователь {username} успешно авторизован")
        except TimeoutException:
            logger.error("Не удалось подтвердить авторизацию")
            print("Ошибка: авторизация не удалась.")
            return False, None, None

        with Session() as session:
            user = session.query(User).filter_by(username=username).first()
            new_session = SessionModel(user_id=user.id)
            session.add(new_session)
            session.commit()

        message = f"✔ Пользователь `{username}` авторизовался"
        asyncio.run_coroutine_threadsafe(send_notification(message), client.loop)
        return True, username, driver
    except TimeoutException:
        logger.error("Превышено время ожидания при авторизации")
        print("Ошибка: превышено время ожидания.")
        return False, None, None
    except NoSuchElementException:
        logger.error("Элемент не найден на странице авторизации")
        print("Ошибка: элемент не найден на странице.")
        return False, None, None
    except Exception as e:
        logger.error(f"Ошибка при авторизации: {e}")
        print(f"Ошибка при авторизации: {e}")
        return False, None, None
    finally:
        pass  # Оставляем driver открытым для дальнейших действий

# Выход из учетной записи
def logout_user(username, driver):
    """Выполняет выход пользователя из учетной записи."""
    if driver is None:
        logger.error("WebDriver не инициализирован")
        print("Ошибка: браузер не доступен.")
        return
    try:
        driver.get("https://cappa.csu.ru/auth/signout/")
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "profile__bar-login")))
        logger.info(f"Пользователь {username} вышел из учетной записи")
        message = f"❌ Пользователь `{username}` вышел из учетной записи"
        asyncio.run_coroutine_threadsafe(send_notification(message), client.loop)
    except TimeoutException:
        logger.error("Не удалось подтвердить выход из учетной записи")
        print("Ошибка: не удалось подтвердить выход.")
    except WebDriverException as e:
        logger.error(f"Ошибка WebDriver при выходе: {e}")
        print(f"Ошибка при выходе: проблема с браузером ({e})")
    except Exception as e:
        logger.error(f"Ошибка при выходе: {e}")
        print(f"Ошибка при выходе: {e}")
    finally:
        driver.quit()

# Главное меню
def main_menu():
    """Отображает меню и управляет действиями пользователя."""
    authorized = False
    current_username = None
    driver = None

    while True:
        print("\nВыберите действие:")
        if not authorized:
            print("1. Зарегистрироваться")
            print("2. Авторизоваться")
            print("3. Выйти из программы")
            choice = input("Введите номер действия (1-3): ").strip()
        else:
            print(f"Вы авторизованы как {current_username}")
            print("1. Выйти из аккаунта")
            print("2. Выйти из программы")
            choice = input("Введите номер действия (1-2): ").strip()

        if not authorized:
            if choice == "1":
                username, user_id, driver = register_user()
                if username and user_id:
                    authorized = True
                    current_username = username
                    print(f"Регистрация успешна для {username}!")
            elif choice == "2":
                success, username, driver = authorize_user()
                if success:
                    authorized = True
                    current_username = username
                    print(f"Авторизация успешна для {username}!")
                else:
                    print("Авторизация не удалась. Попробуйте снова.")
            elif choice == "3":
                print("Выход из программы...")
                break
            else:
                print("Неверный выбор, попробуйте снова.")
        else:
            if choice == "1":
                logout_user(current_username, driver)
                authorized = False
                current_username = None
                driver = None
            elif choice == "2":
                logout_user(current_username, driver)
                print("Выход из программы...")
                break
            else:
                print("Неверный выбор, попробуйте снова.")

# Основной блок программы
if __name__ == "__main__":
    # Запуск Telegram-клиента через асинхронную функцию
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_telegram_client())

    # Запуск цикла событий в отдельном потоке
    loop_thread = threading.Thread(target=client.loop.run_forever)
    loop_thread.start()

    try:
        # Запуск главного меню
        main_menu()
    finally:
        # Остановка цикла событий и завершение работы
        client.loop.call_soon_threadsafe(client.loop.stop)
        loop_thread.join()
        loop.run_until_complete(stop_telegram_client())
        logger.info("Программа завершена")