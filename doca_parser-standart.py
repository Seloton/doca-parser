from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
# [NEW] инструменты для явных ожиданий вместо time.sleep
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    NoSuchFrameException,
)
import pandas as pd
import time
import json
import os
import re


# ---------------------------------------------------------------------------
# [NEW] Константы вынесены наверх, чтобы их было легко поправить под сайт.
# ВАЖНО: PATIENT_LINK_XPATH сейчас "//a" (любая ссылка), как было в исходнике.
# Лучше заменить на точный XPath ссылки пациента, иначе можно кликнуть
# по случайной ссылке (меню, "Назад" и т.п.).
# ---------------------------------------------------------------------------
TIMEOUT = 20                                    # [NEW] общий таймаут ожиданий, сек
FRAME_MENU = "//frame[@name='main_menu_window']"
FRAME_DOC = "//frame[@name='doc_window']"
PATIENT_LINK_XPATH = "//a"
HISTORY_LINK_XPATH = "//td[@title='№ Истории болезни']/a"
MAX_DEBUG = 50


class DocaParser(object):
    def __init__(self, driver, config, patients, log_index=0, doca_url=None):
        self.driver = driver
        self.patients = patients
        self.cookies = config
        self.log_index = log_index
        self.errors = []
        self.doca_url = doca_url
        # [NEW] папка для результатов создаётся автоматически,
        # иначе save_to_file падает, если папки 'analis' нет
        os.makedirs('analis', exist_ok=True)
        self.debug_count = 0

    # -----------------------------------------------------------------------
    # [CHANGED] Логирование. Раньше ошибки копились в списке и писались в файл
    # только в конце parse(): при падении/Ctrl+C за 10 часов всё терялось.
    # Теперь каждая ошибка пишется в файл сразу. Добавлен encoding='utf-8'
    # (без него на Windows русские символы в логе могут вызвать ошибку).
    # -----------------------------------------------------------------------
    def log_error(self, message):
        self.errors.append(message)
        try:
            with open(f'logs_{self.log_index}.txt', 'a', encoding='utf-8') as file:
                file.write(message)
        except Exception as e:
            print('Не удалось записать лог:', e)

    # -----------------------------------------------------------------------
    # [NEW] Блок вспомогательных методов для ожиданий.
    # Зачем: страница и фреймы грузятся асинхронно. find_element/find_elements
    # сразу после click() часто видят ещё не загруженную страницу, и парсер
    # решает, что "ничего не найдено". Здесь мы ждём конкретные события.
    # -----------------------------------------------------------------------
    def wait(self, timeout=TIMEOUT):
        return WebDriverWait(self.driver, timeout)

    def wait_page_ready(self, timeout=TIMEOUT):
        """Ждём document.readyState == 'complete' в текущем фрейме."""
        self.wait(timeout).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )

    def find_in_frame(self, frame_xpath, xpath, many=False, timeout=TIMEOUT):
        """
        Каждый раз заново заходит во фрейм (после перезагрузки фрейма старые
        элементы становятся stale) и ждёт появления элемента/элементов.
        При таймауте бросает TimeoutException.
        """
        def _try(d):
            try:
                d.switch_to.default_content()
                if frame_xpath:
                    d.switch_to.frame(d.find_element(By.XPATH, frame_xpath))
                els = d.find_elements(By.XPATH, xpath)
                if many:
                    return els if els else False
                return els[0] if els else False
            except (NoSuchElementException, NoSuchFrameException,
                    StaleElementReferenceException):
                return False
        return self.wait(timeout).until(_try)

    def click_and_wait_reload(self, element, timeout=TIMEOUT):
        """
        Клик и ожидание смены контента: ждём, пока старый элемент исчезнет
        из DOM (staleness_of). URL при этом не важен: адрес у сайта один,
        меняется только содержимое фреймов.
        """
        element.click()
        try:
            self.wait(timeout).until(EC.staleness_of(element))
            print('  [wait] страница сменилась')
        except TimeoutException:
            # контент мог обновиться без удаления элемента (AJAX), идём дальше,
            # а следующий find_in_frame дождётся нужного элемента
            print('  [wait] stale не сработал, контент обновился иначе')
        try:
            self.wait_page_ready(5)
        except Exception:
            pass  # контекст фрейма мог сброситься, это нормально

    def save_debug(self, tag):
        if self.debug_count >= MAX_DEBUG:
            return
        self.debug_count += 1
        os.makedirs('debug', exist_ok=True)  # отдельная папка, не засоряет рабочую
        tag = re.sub(r'[\\/:*?"<>|\s]+', '_', tag)
        try:
            self.driver.save_screenshot(os.path.join('debug', f'debug_{tag}.png'))
        except Exception:
            pass
        try:
            with open(os.path.join('debug', f'debug_{tag}.html'), 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
        except Exception:
            pass

    # -----------------------------------------------------------------------

    def get_payload(self, data):
        cod = data["cod"]
        name = data["Name"]
        fio = str(name).split()
        if len(fio) >= 3:
            payload = {
                'surname': fio[0],
                'name': fio[1],
                # [CHANGED] отчество собираем из всех оставшихся слов
                # ("Иванов Иван Иванович оглы"), раньше хвост терялся
                'patronymic': ' '.join(fio[2:]),
                'cod': cod
            }
        elif len(fio) == 2:
            payload = {
                'surname': fio[0],
                'name': fio[1],
                'patronymic': '',
                'cod': cod
            }
        elif len(fio) == 1:
            payload = {
                'surname': fio[0],
                'name': '',
                'patronymic': '',
                'cod': cod
            }
        else:
            return None
        return payload

    def split_codes(self, cod_value):
        if pd.isna(cod_value):
            return []
        cod_string = str(cod_value).strip()
        # [CHANGED] отсекаем строку 'nan' (если NaN превратился в текст)
        if not cod_string or cod_string.lower() == 'nan':
            return []
        codes = []
        for code in cod_string.split(','):
            code = code.strip()
            # [NEW] страховка от float: "12345.0" -> "12345"
            if code.endswith('.0'):
                code = code[:-2]
            if code:
                codes.append(code)
        return codes

    # [NEW] Имя файла вынесено в метод: оно нужно и для сохранения,
    # и для пропуска уже обработанных кодов при повторном запуске.
    # Запрещённые в Windows символы заменяются на '_'.
    def build_file_name(self, patient):
        raw = (
            patient['surname']
            + patient['name']
            + patient['patronymic']
            + '_analyzes_'
            + str(patient['cod'])
            + '.html'
        )
        return re.sub(r'[\\/:*?"<>|]', '_', raw)

    def switch_to_frame_by_xpath(self, xpath):
        print(f'Переключение фрейма {xpath}...')
        self.driver.switch_to.frame(self.driver.find_element(By.XPATH, xpath))

    def parse(self, start=0, end=0):
        if end <= 0:
            end = len(self.patients)
        total_an = 0
        total_his = 0
        errors = 0
        total_patients = end - start
        for i in range(start, end):
            print(f'# {i - start + 1} из {total_patients} [id: {i}]')
            patient_row = self.patients.iloc[i]
            codes = self.split_codes(patient_row["Cod"])
            print(f'Пациент: {patient_row["Name"]} | 'f'Кодов: {len(codes)}')
            if len(codes) == 0:
                print('У пациента нет кодов, пропускаем...')
                errors += 1
                continue
            for cod_index, cod in enumerate(codes):
                print(f'  Код {cod_index}: {cod} 'f'({cod_index + 1}/{len(codes)})')
                payload = self.get_payload({
                    "cod": cod,
                    "Name": patient_row["Name"]
                })
                if payload is None:
                    print('  Не удалось создать данные пациента')
                    errors += 1
                    continue

                # [NEW] Возобновление: если файл для этого кода уже сохранён
                # (прошлый запуск), пропускаем. Не нужно начинать 10 часов заново.
                if os.path.exists(os.path.join('analis', self.build_file_name(payload))):
                    print('  Файл уже существует, пропускаем...')
                    continue

                try:
                    self.open()
                    info = self.find_patient_info(payload, cod_index=cod_index)
                    if info:
                        total_an += info[0]
                        total_his += info[1]
                    else:
                        # [CHANGED] раньше неудача внутри find_patient_info
                        # (return 0) не попадала в счётчик ошибок
                        errors += 1
                except Exception as e:
                    errors += 1
                    self.log_error(
                        f'[{time.ctime()} in parse] '
                        f'[{patient_row["Name"]}] '
                        f'[cod={cod}] {e}\n'
                    )
                    print(e)
        # [CHANGED] write_log в конце удалён: логи пишутся сразу в log_error
        print(f'Разобрано пациентов: {total_patients - errors} / {total_patients}')
        print(f'Удалось получить - анализы: {total_an}, ИБ: {total_his}')

    def open(self):
        doca_url = self.doca_url
        print(f'Открытие {doca_url}...')
        try:
            self.driver.get(doca_url)
            for cookie in self.cookies:
                self.driver.add_cookie({'name': cookie['name'], 'value': cookie['value']})
            self.driver.get(doca_url)
            # [NEW] ждём, пока главное меню реально загрузится
            self.find_in_frame(FRAME_MENU, "//*[@title='Архив']")
        except Exception as e:
            self.log_error(f'[{time.ctime()} in open] {e}\n')
            print(e)
            # [NEW] пробрасываем ошибку: раньше исключение глоталось, и код
            # шёл дальше по незагруженной странице, давая ложное "не найдено"
            raise

    def save_to_file(self, file_name, text):
        folder = 'analis'
        file_path = os.path.join(folder, file_name)
        print(f'Сохранение в файл {file_path}...')
        # [CHANGED] errors='replace': символ вне cp1251 раньше вызывал
        # UnicodeEncodeError, и результат терялся
        with open(file_path, 'w', encoding='cp1251', errors='replace') as file:
            file.write(text)

    def save_to_json(self, file_name, data):
        print(f'Сохранение в файл {file_name}...')
        with open(file_name, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False)

    # [CHANGED] Полностью переписан: ожидания вместо мгновенных find_element,
    # повтор при сбоях (retries), различие между "не загрузилось" и
    # "пациента действительно нет".
    def find_patient_info(self, patient, history_num=1, cod_index=0, retries=2):
        fio = patient["surname"] + patient["name"] + patient["patronymic"]
        print(f'Поиск информации о пациенте [{fio}] по коду [{patient["cod"]}]...')

        last_error = None
        for attempt in range(1, retries + 1):
            try:
                # 1. Кнопка "Архив" (ждём появления в меню)
                archive_btn = self.find_in_frame(FRAME_MENU, "//*[@title='Архив']")
                archive_btn.click()

                # 2. Форма поиска: ждём, пока она появится в doc_window
                surname = self.find_in_frame(FRAME_DOC, "//input[@name='fam']")
                name = self.driver.find_element(By.XPATH, "//input[@name='nam']")
                patronymic = self.driver.find_element(By.XPATH, "//input[@name='ots']")
                cod_input = self.driver.find_element(By.XPATH, "//input[@name='nom_ib']")
                submit_btn = self.driver.find_element(By.XPATH, "//input[@name='Submit']")

                for el, val in ((surname, patient['surname']),
                                (name, patient['name']),
                                (patronymic, patient['patronymic'])):
                    el.clear()
                    if len(val) > 0:
                        el.send_keys(val)

                cod_input.click()
                cod_input.send_keys(Keys.CONTROL + "a")
                cod_input.send_keys(Keys.DELETE)
                self.driver.execute_script("arguments[0].value = '';", cod_input)
                if str(patient['cod']).strip():
                    cod_input.send_keys(str(patient['cod']))

                # 3. Отправка формы и ожидание результатов поиска
                self.click_and_wait_reload(submit_btn)

                try:
                    patient_links = self.find_in_frame(
                        FRAME_DOC, PATIENT_LINK_XPATH, many=True, timeout=15)
                except TimeoutException:
                    # страница загрузилась, но ссылок нет: пациента реально нет,
                    # повторять смысла нет
                    raise LookupError(f'Не найден пациент для кода {patient["cod"]}')

                self.click_and_wait_reload(patient_links[0])

                # 4. Список историй болезни
                try:
                    hos_links = self.find_in_frame(
                        FRAME_DOC, HISTORY_LINK_XPATH, many=True, timeout=10)
                except TimeoutException:
                    try:
                        hos_links = self.find_in_frame(
                            FRAME_DOC, "//a", many=True, timeout=5)
                    except TimeoutException:
                        raise LookupError(
                            f'Не найдена история болезни для кода {patient["cod"]}')

                print(f'История {history_num} из {len(hos_links)}')
                hos = self.hos_info(hos_links[0], patient, history_num - 1, cod_index)
                return [hos[0], hos[1], len(hos_links)]

            except LookupError as e:
                last_error = e
                break
            except Exception as e:
                last_error = e
                print(f'Попытка {attempt}/{retries} не удалась: {e}')
                if attempt < retries:
                    # [NEW] перед повтором начинаем с чистой страницы
                    try:
                        self.open()
                    except Exception:
                        pass

        self.log_error(
            f'[{time.ctime()} in find_patient_info] [{fio}] '
            f'[cod={patient["cod"]}] {last_error}\n'
        )
        print(last_error)
        self.save_debug(f'{fio}_{patient["cod"]}')   # [NEW] скриншот + HTML
        return 0

    def hos_info(self, hos_link, patient, num=0, cod_index=0):
        # [CHANGED] после клика ждём смену страницы
        self.click_and_wait_reload(hos_link)
        an = self.analyzes(patient, num, cod_index)
        his = self.history(patient, num)
        return [an, his]

    def history(self, patient, num):
        # Заглушка, чтобы не падало
        return 0

    # [CHANGED] ожидания вместо time.sleep(1); если анализы не найдены,
    # пустая страница больше не сохраняется как "успех".
    def analyzes(self, patient, num=0, cod_index=0):
        print(f'Получение анализов для кода [{patient["cod"]}]...')
        fio = patient["surname"] + patient["name"] + patient["patronymic"]
        try:
            # вкладка анализов; если sid28 не в doc_window, поменяйте фрейм
            an_link = self.find_in_frame(FRAME_DOC, "//*[@id='sid28']")
            an_link.click()

            # [CHANGED] вместо sleep(1) ждём появления таблицы анализов
            self.find_in_frame(FRAME_DOC, "//form[@name='analviewform']//table//tr")
            rows = self.driver.find_elements(
                By.XPATH, "//form[@name='analviewform']//table//tr")

            found_analysis = False
            for row in rows:
                tds = row.find_elements(By.TAG_NAME, "td")
                if len(tds) == 5:
                    last_td_text = tds[4].text.strip()
                    if str(last_td_text) == str(patient['cod']):
                        checkbox = tds[0].find_element(By.TAG_NAME, "input")
                        checkbox.click()
                        found_analysis = True

            if not found_analysis:
                # [CHANGED] раньше только print и сохранение пустой страницы
                raise LookupError(f'Анализы для кода {patient["cod"]} не найдены')

            view_btn = self.driver.find_element(
                By.XPATH, "//input[@value='Просмотреть отмеченные вместе']")
            self.click_and_wait_reload(view_btn)

            # [NEW] заново заходим во фрейм и ждём body, чтобы page_source
            # был именно страницей с результатами, а не промежуточной
            self.find_in_frame(FRAME_DOC, "//body")

            self.save_to_file(self.build_file_name(patient), self.driver.page_source)
            return 1
        except Exception as e:
            self.log_error(
                f'[{time.ctime()} in analyzes] '
                f'[{fio}{patient["cod"]}] {e}\n'
            )
            print(e)
            self.save_debug(f'analyzes_{fio}_{patient["cod"]}')   # [NEW]
            return 0

    def go_next(self):
        print('Переход далее...')
        try:
            next_btn = self.driver.find_element(By.XPATH, "//input[@onclick='GoNext()']")
            next_btn.click()
        except Exception as e:
            self.log_error(f'[{time.ctime()} in next] {e}\n')
            print(e)


def load_config(file_name):
    print('Загрузка конфигурации...')
    with open(file_name, 'r') as file:
        data = json.load(file)
    return data


def load_patients(xlsx):
    print('Загрузка списка пациентов....')
    # [CHANGED] dtype=str + fillna: коды не превращаются в float,
    # пустые ячейки не становятся 'nan'. Если у вас уже своя нормализация
    # данных, эта строка просто не помешает.
    patients = pd.read_excel(xlsx, dtype=str).fillna('')
    return patients


def main(shutdown=False, headless=True):
    print('Добро пожаловать в DocA Parser!\n'
        'Пожалуйста, подождите пока программа загрузит необходимые ресурсы...\n')
    options = webdriver.ChromeOptions()
    # [CHANGED] options.headless устарел в новых версиях Selenium
    if headless:
        options.add_argument('--headless=new')
    config_data = load_config('config.json')
    cookies = config_data['cookie']
    doca_url = config_data['doca_url']
    patients = load_patients('patients.xlsx')
    driver = webdriver.Chrome(options=options)
    parser = DocaParser(driver, cookies, patients, doca_url=doca_url)
    print(
        'Доступные команды:\n'
        '  exit\n'
        '  start [start=0, end=max]\n'
        '  count\n'
        '  print'
    )
    while True:
        cmd = input('> ').split()
        try:
            if not cmd:
                continue
            if cmd[0] == 'exit':
                break
            elif cmd[0] == 'start':
                start_time = time.perf_counter()
                if len(cmd) > 2:
                    parser.parse(int(cmd[1]) - 1, int(cmd[2]))
                elif len(cmd) > 1:
                    parser.parse(end=int(cmd[1]))
                else:
                    parser.parse()
                result_time = (time.perf_counter() - start_time)
                print('Время выполнения программы %.2f секунд'% result_time)
            elif cmd[0] == 'count':
                print(len(patients.index))
            elif cmd[0] == 'print':
                print(patients)
            else:
                print('Неверная команда!')
        except Exception as e:
            print('Ошибка :', e)
    # [CHANGED] driver.quit() теперь выполняется до shutdown:
    # раньше при shutdown=True браузер не закрывался корректно
    driver.quit()
    if shutdown:
        os.system('shutdown /s /t 1')


if __name__ == "__main__":
    main()