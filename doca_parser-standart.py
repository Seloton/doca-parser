from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import pandas as pd
import time
import json
import os


class DocaParser(object):
    def __init__(self, driver, config, patients, log_index=0, doca_url=None):
        self.driver = driver
        self.patients = patients
        self.cookies = config
        self.log_index = log_index
        self.errors = []
        self.doca_url = doca_url

    def write_log(self, index):
        with open(f'logs_{index}.txt', 'a') as file:
            file.writelines(self.errors)

    def get_payload(self, data):
        payload = None
        cod = data["cod"]
        name = data["Name"]
        fio = str(name).split()
        if len(fio) == 2:
            if len(fio[1]) == 2:
                payload = {
                    'name': fio[1][0],
                    'surname': fio[0],
                    'patronymic': fio[1][1],
                    'cod': cod
                }
            elif len(fio[1]) == 1:
                payload = {
                    'name': fio[1][0],
                    'surname': fio[0],
                    'patronymic': '',
                    'cod': cod
                }
        else:
            payload = {
                'name': '',
                'surname': fio[0],
                'patronymic': '',
                'cod': cod
            }
        return payload

    def split_codes(self, cod_value):
        if pd.isna(cod_value):
            return []
        # Приводим к строке
        cod_string = str(cod_value).strip()
        if not cod_string:
            return []
        # Разбиваем по запятой
        codes = cod_string.split(',')
        # Убираем пробелы и пустые значения
        codes = [
            code.strip()
            for code in codes
            if code.strip()
        ]
        return codes

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
            # Получаем строку пациента
            patient_row = self.patients.iloc[i]
            # Получаем все коды этого пациента
            codes = self.split_codes(patient_row["Cod"])
            print(f'Пациент: {patient_row["Name"]} | 'f'Кодов: {len(codes)}')
            # Если кодов нет
            if len(codes) == 0:
                print('У пациента нет кодов, пропускаем...')
                errors += 1
                continue
            # Сначала полностью обрабатываем ВСЕ коды текущего пациента
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
                try:
                    self.open()
                    info = self.find_patient_info(payload, cod_index=cod_index)
                    if info:
                        total_an += info[0]
                        total_his += info[1]
                except Exception as e:
                    errors += 1
                    self.errors.append(
                        f'[{time.ctime()} in parse] '
                        f'[{patient_row["Name"]}] '
                        f'[cod={cod}] {e}\n'
                    )
                    print(e)
        if len(self.errors) > 0:
            self.write_log(self.log_index)
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
        except Exception as e:
            self.errors.append(f'[{time.ctime()} in open] {e}\n')
            print(e)


    def save_to_file(self, file_name, text):
        print(f'Сохранение в файл {file_name}...')
        with open(file_name, 'w', encoding='cp1251') as file:
            file.write(text)


    def save_to_json(self, file_name, data):
        print(f'Сохранение в файл {file_name}...')
        with open(file_name, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False)


    def find_patient_info(self, patient, history_num=1, cod_index=0):
        print(
            f'Поиск информации о пациенте '
            f'[{patient["surname"] + patient["name"] + patient["patronymic"]}] '
            f'по коду [{patient["cod"]}]...'
        )
        try:
            self.switch_to_frame_by_xpath("//frame[@name='main_menu_window']")
            archive_btn = self.driver.find_element(By.XPATH, "//*[@title='Архив']")
            archive_btn.click()
            self.driver.switch_to.default_content()
            self.switch_to_frame_by_xpath("//frame[@name='doc_window']")
            surname = self.driver.find_element(By.XPATH, "//input[@name='fam']")
            name = self.driver.find_element(By.XPATH, "//input[@name='nam']")
            patronymic = self.driver.find_element(By.XPATH, "//input[@name='ots']")
            cod_input = self.driver.find_element(By.XPATH, "//input[@name='nom_ib']")
            submit_btn = self.driver.find_element(By.XPATH, "//input[@name='Submit']")
            # Фамилия
            surname.clear()
            if len(patient['surname']) > 0:
                surname.send_keys(patient['surname'])
            # Имя
            name.clear()
            if len(patient['name']) > 0:
                name.send_keys(patient['name'])
            # Отчество
            patronymic.clear()
            if len(patient['patronymic']) > 0:
                patronymic.send_keys(patient['patronymic'])
            # Полностью очищаем поле кода
            cod_input.click()
            cod_input.send_keys(Keys.CONTROL + "a")
            cod_input.send_keys(Keys.DELETE)
            self.driver.execute_script("arguments[0].value = '';", cod_input)
            # Вводим текущий код
            if str(patient['cod']).strip():
                cod_input.send_keys(str(patient['cod']))
            submit_btn.click()
            patient_links = self.driver.find_elements(By.TAG_NAME, 'a')
            if len(patient_links) == 0:
                raise Exception(f'Не найден пациент для кода {patient["cod"]}')
            patient_links[0].click()
            hos_links = self.driver.find_elements(By.XPATH, "//td[@title='№ Истории болезни']/a")
            if len(hos_links) == 0:
                hos_links = self.driver.find_elements(By.TAG_NAME, 'a')
            if len(hos_links) == 0:
                raise Exception(f'Не найдена история болезни для кода {patient["cod"]}')
            print(f'История {history_num} из {len(hos_links)}')
            hos = self.hos_info(hos_links[0], patient, history_num - 1, cod_index)
            result = [hos[0], hos[1], len(hos_links)]
            return result
        except Exception as e:
            self.errors.append(
                f'[{time.ctime()} in find_patient_info] '
                f'[{patient["surname"] + patient["name"] + patient["patronymic"]}] '
                f'[cod={patient["cod"]}] {e}\n'
            )
            print(e)
            return 0


    def hos_info(self, hos_link, patient, num=0, cod_index=0):
        hos_link.click()
        an = self.analyzes(patient, num, cod_index)
        his = self.history(patient, num)
        return [an, his]

    def history(self, patient, num):
        # Заглушка, чтобы не падало
        return 0

    def analyzes(self, patient, num=0, cod_index=0):
        print(
            f'Получение анализов для кода '
            f'[{patient["cod"]}]...'
        )
        try:
            an_link = self.driver.find_element(By.ID, 'sid28')
            an_link.click()
            time.sleep(1)
            rows = self.driver.find_elements(By.XPATH, "//form[@name='analviewform']//table//tr")
            found_analysis = False
            for row in rows:
                tds = row.find_elements(By.TAG_NAME, "td")
                if len(tds) == 5:
                    last_td_text = tds[4].text.strip()
                    # Сравниваем с ТЕКУЩИМ кодом
                    if str(last_td_text) == str(patient['cod']):
                        checkbox = tds[0].find_element(By.TAG_NAME, "input")
                        checkbox.click()
                        found_analysis = True
            if not found_analysis:
                print(f'Анализы для кода {patient["cod"]} не найдены')
            view_btn = self.driver.find_element(By.XPATH, "//input[@value='Просмотреть отмеченные вместе']")
            view_btn.click()
            time.sleep(1)

            file_name = (
                patient['surname']
                + patient['name']
                + patient['patronymic']
                + '_analyzes_'
                + str(num)
                + '_'
                + str(cod_index)
                + '.html'
            )
            self.save_to_file(file_name, self.driver.page_source)
            return 1
        except Exception as e:
            self.errors.append(
                f'[{time.ctime()} in analyzes] '
                f'[{patient["surname"] + patient["name"] + patient["patronymic"]}'
                f'{patient["cod"]}] {e}\n'
            )
            print(e)
            return 0


    def go_next(self):
        print('Переход далее...')
        try:
            next_btn = self.driver.find_element(By.XPATH, "//input[@onclick='GoNext()']")
            next_btn.click()
        except Exception as e:
            self.errors.append(f'[{time.ctime()} in next] {e}\n')
            print(e)


def load_config(file_name):
    print('Загрузка конфигурации...')
    with open(file_name, 'r') as file:
        data = json.load(file)
    return data


def load_patients(xlsx):
    print('Загрузка списка пациентов....')
    patients = pd.read_excel(xlsx)
    return patients


def main(shutdown=False, headless=True):
    print('Добро пожаловать в DocA Parser!\n'
        'Пожалуйста, подождите пока программа загрузит необходимые ресурсы...\n')
    options = webdriver.ChromeOptions()
    options.headless = headless
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
    if shutdown:
        os.system('shutdown /s /t 1')
    driver.quit()


if __name__ == "__main__":
    main()