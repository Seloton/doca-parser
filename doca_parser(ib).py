from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import pandas as pd
import time
import json
import os

class DocaParser(object):

    def __init__(self, driver, config, patients, log_index=0, output_file='results.xlsx'):
        self.driver = driver
        self.patients = patients
        self.cookies = config
        self.log_index = log_index
        self.errors = []
        self.output_file = output_file
        self.buffer = []

    def _append_to_excel(self, new_rows):
        """Добавляет новые строки в существующий Excel-файл или создаёт новый."""
        if not new_rows:
            return
        new_df = pd.DataFrame(new_rows)
        if os.path.exists(self.output_file):
            try:
                existing_df = pd.read_excel(self.output_file)
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            except Exception:
                # Если файл повреждён или пуст, начинаем заново
                combined_df = new_df
        else:
            combined_df = new_df
        combined_df.to_excel(self.output_file, index=False)
        print(f'Промежуточное сохранение: {len(new_rows)} записей добавлено в {self.output_file}')


    def write_log(self, index):
        with open(f'logs_{index}.txt', 'a') as file:
            file.writelines(self.errors)

    def get_payload(self, data):
        """Извлекает ФИО и год рождения. Никакого cod!"""
        payload = None
        name = data["Name"]
        year = data["Year"]
        if pd.isna(year):
            return None
        fio = name.split()
        if len(fio) == 2:
            if len(fio[1]) == 2:
                payload = {
                    'name': fio[1][0],
                    'surname': fio[0],
                    'patronymic': fio[1][1],
                    'year': int(year)
                }
            elif len(fio[1]) == 1:
                payload = {
                    'name': fio[1][0],
                    'surname': fio[0],
                    'patronymic': '',
                    'year': int(year)
                }
        else:
            payload = {
                'name': '',
                'surname': fio[0],
                'patronymic': '',
                'year': int(year)
            }
        return payload

    def switch_to_frame_by_xpath(self, xpath):
        print(f'Переключение фрейма {xpath}...')
        self.driver.switch_to.frame(self.driver.find_element(By.XPATH, xpath))

    def parse(self, start=0, end=0):
        if end <= 0:
            end = len(self.patients)
        total_patients = end - start
        for i in range(start, end):
            print(f'# {i - start + 1} из {total_patients} [id: {i}]')
            payload = self.get_payload({
                "Name": self.patients["Name"][i],
                "Year": self.patients["Year"][i]
            })
            if payload is None:
                row = {
                    'Name': self.patients["Name"][i],
                    'Year': self.patients["Year"][i] if not pd.isna(self.patients["Year"][i]) else '',
                    'Links': 'Нет года рождения'
                }
                self.buffer.append(row)
                continue

            try:
                self.open()
                links_texts = self.find_patient_info(payload)
                if not links_texts:
                    row = {
                        'Name': self.patients["Name"][i],
                        'Year': payload['year'],
                        'Links': 'Ссылка не найдена'
                    }
                else:
                    row = {
                        'Name': self.patients["Name"][i],
                        'Year': payload['year'],
                        'Links': '; '.join(links_texts)
                    }
                self.buffer.append(row)
            except Exception as e:
                self.errors.append(f'[{time.ctime()}] {e}')
                row = {
                    'Name': self.patients["Name"][i],
                    'Year': payload['year'] if payload else '',
                    'Links': f'Ошибка: {e}'
                }
                self.buffer.append(row)

            # Сохраняем каждые 100 записей (или последний блок)
            if len(self.buffer) >= 100:
                self._append_to_excel(self.buffer)
                self.buffer.clear()

        # Сохраняем оставшиеся записи после окончания цикла
        if self.buffer:
            self._append_to_excel(self.buffer)
            self.buffer.clear()

        if self.errors:
            self.write_log(self.log_index)

    def open(self):
        doca_url = 'http://172.20.0.223/docaplus/main/main.php?first=1'
        print(f'Открытие {doca_url}...')
        try:
            self.driver.get(doca_url)
            for cookie in self.cookies:
                self.driver.add_cookie({'name': cookie['name'], 'value': cookie['value']})
            self.driver.get(doca_url)
        except Exception as e:
            self.errors.append(f'[{time.ctime()}] {e}')
            print(e)

    def find_patient_info(self, patient):
        print(f'Поиск информации о пациенте [{patient["surname"]} {patient["name"]} {patient["patronymic"]}]...')
        try:
            self.switch_to_frame_by_xpath("//frame[@name='main_menu_window']")
            archive_btn = self.driver.find_element(By.XPATH, "//*[@title='Архив']")
            archive_btn.click()
            self.driver.switch_to.default_content()
            self.switch_to_frame_by_xpath("//frame[@name='doc_window']")

            surname = self.driver.find_element(By.XPATH, "//input[@name='fam']")
            name = self.driver.find_element(By.XPATH, "//input[@name='nam']")
            patronymic = self.driver.find_element(By.XPATH, "//input[@name='ots']")
            year_input = self.driver.find_element(By.XPATH, "//input[@name='year']")
            submit_btn = self.driver.find_element(By.XPATH, "//input[@name='Submit']")

            surname.clear()
            if patient['surname']:
                surname.send_keys(patient['surname'])
            name.clear()
            if patient['name']:
                name.send_keys(patient['name'])
            patronymic.clear()
            if patient['patronymic']:
                patronymic.send_keys(patient['patronymic'])

            year_input.click()
            year_input.send_keys(Keys.CONTROL + "a")
            year_input.send_keys(Keys.DELETE)
            self.driver.execute_script("arguments[0].value = '';", year_input)
            if patient['year']:
                year_input.send_keys(str(patient['year']))

            submit_btn.click()
            time.sleep(1)

            patient_links = self.driver.find_elements(By.TAG_NAME, 'a')
            if not patient_links:
                print('Ссылка на пациента не найдена')
                return None

            patient_links[0].click()
            time.sleep(1)

            all_links = self.driver.find_elements(By.TAG_NAME, 'a')
            texts = [link.text.strip() for link in all_links if link.text.strip()]
            return texts

        except Exception as e:
            self.errors.append(
                f'[{time.ctime()} in find_patient_info] [{patient["surname"]} {patient["name"]} {patient["patronymic"]}] {e}')
            print(e)
            return None

def load_config(file_name):
    print('Загрузка конфигурации...')
    with open(file_name, 'r') as file:
        data = json.load(file)
    return data['cookie']

def load_patients(xlsx):
    print('Загрузка списка пациентов....')
    patients = pd.read_excel(xlsx)
    return patients

def main(shutdown=False, headless=True):
    print('Добро пожаловать в DocA Parser!\nПожалуйста, подождите пока программа загрузит необходимые ресурсы...\n')
    options = webdriver.ChromeOptions()
    options.headless = headless
    config = load_config('config.json')
    patients = load_patients('patients.xlsx')
    driver = webdriver.Chrome(options=options)
    parser = DocaParser(driver, config, patients)
    print('Доступные команды:\n  exit\n  start [start=0, end=max]\n  count\n  print')
    while True:
        user_input = input('> ').strip()
        if not user_input:          # пустой ввод игнорируем
            continue
        cmd = user_input.split()
        try:
            if cmd[0] == 'exit':
                break
            elif cmd[0] == 'start':
                start_time = time.perf_counter()
                if len(cmd) > 2:
                    parser.parse(int(cmd[1])-1, int(cmd[2]))
                elif len(cmd) > 1:
                    parser.parse(end=int(cmd[1]))
                else:
                    parser.parse()
                result_time = time.perf_counter() - start_time
                print('Время выполнения программы %.2f секунд' % result_time)
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