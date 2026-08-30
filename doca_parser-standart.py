from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import pandas as pd
import time
import json
import os


class DocaParser(object):

    def __init__(self, driver, config, patients, log_index=0):
        self.driver = driver
        self.patients = patients
        self.cookies = config
        self.log_index = log_index
        self.errors = []

    def write_log(self, index):
        with open(f'logs_{index}.txt', 'a') as file:
            file.writelines(self.errors)
    
    def get_payload(self, data):
        payload = None
        cod = data["cod"]
        name = data["Name"]
        fio = name.split()
        if len(fio) == 2:
            if( len(fio[1]) == 2 ): 
                payload = {
	     	          	'name': fio[1][0],
				        'surname': fio[0],
                		'patronymic': fio[1][1],
				        'cod':cod
            		}
            elif( len(fio[1]) == 1 ):
                payload = {
	     	          	'name': fio[1][0],
				        'surname': fio[0],
                		'patronymic': '',
				        'cod':cod
            		}
        else:
            payload = {
	     	          	'name': '',
			        	'surname': fio[0],
                		'patronymic': '',
				        'cod':cod
            		 }

        return payload

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
            #data = self.patients[i].split()
            payload = self.get_payload({ "cod":self.patients["Cod"][i], "Name":self.patients["Name"][i] })
            
            if payload is not None:
                try:
                    self.open()
                    info = self.find_patient_info(payload)
                    
                    total_an += info[0]
                    total_his += info[1]
                    
                    
                    # histories_count = info[2] - 1
                    # while histories_count > 0:
                    #     self.open()
                    #     info = self.find_patient_info(payload, histories_count)
                    #     total_an += info[0]
                    #     total_his += info[1]
                    #     histories_count -= 1
                except Exception as e:
                    errors += 1
        if len(self.errors) > 0:
            self.write_log(self.log_index)
        print(f'Разобранно {total_patients - errors} / {total_patients}')
        print(f'Удалось получить - анализы: {total_an}, ИБ: {total_his}')

    def open(self):
        doca_url = ''
        print(f'Открытие {doca_url}...')
        try:
            self.driver.get(doca_url)
            for cookie in self.cookies:
                self.driver.add_cookie({'name': cookie['name'], 'value': cookie['value']})
            self.driver.get(doca_url)
        except Exception as e:
            self.errors.append(f'[{time.ctime()}] {e}')
            print(e)
    
    def save_to_file(self, file_name, text):
        print(f'Сохранение в файл {file_name}...')
        with open(file_name, 'w', encoding='cp1251') as file:
            file.write(text)
    
    def save_to_json(self, file_name, data):
        print(f'Сохранение в файл{file_name}...')
        with open(file_name, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False)

    def find_patient_info(self, patient, history_num=1):
        print(f'Поиск информации о пациенте [{patient["surname"] + patient["name"] + patient["patronymic"]}]...')
        try:
            self.switch_to_frame_by_xpath("//frame[@name='main_menu_window']")
            archive_btn = self.driver.find_element(By.XPATH, "//*[@title='Архив']")
            archive_btn.click()
            self.driver.switch_to.default_content()
            self.switch_to_frame_by_xpath("//frame[@name='doc_window']")
            surname = self.driver.find_element(By.XPATH, "//input[@name='fam']")
            name = self.driver.find_element(By.XPATH, "//input[@name='nam']")
            patronymic = self.driver.find_element(By.XPATH, "//input[@name='ots']")
            cod_input = self.driver.find_element(By.XPATH,
                                                 "//input[@name='nom_ib']")  # переименовал, чтобы не конфликтовать
            submit_btn = self.driver.find_element(By.XPATH, "//input[@name='Submit']")
            surname.clear()
            if len(patient['surname']) > 0:
                surname.send_keys(patient['surname'])
            name.clear()
            if len(patient['name']) > 0:
                name.send_keys(patient['name'])
            patronymic.clear()
            if len(patient['patronymic']) > 0:
                patronymic.send_keys(patient['patronymic'])
            # Всегда очищаем поле (даже если cod == 0)
            cod_input.click()  # фокус на элементе
            cod_input.send_keys(Keys.CONTROL + "a")  # выделить всё
            cod_input.send_keys(Keys.DELETE)  # удалить
            # Дополнительная страховка через JavaScript
            self.driver.execute_script("arguments[0].value = '';", cod_input)
            # Вводим новое значение только если cod > 0
            if int(patient['cod']) > 0:
                cod_input.send_keys(str(patient['cod']))
            submit_btn.click()
            patient_links = self.driver.find_elements(By.TAG_NAME, 'a')
            patient_links[0].click()
            hos_links = self.driver.find_elements(By.XPATH, "//td[@title='№ Истории болезни']/a")
            if len(hos_links) == 0:  # правильная проверка
                hos_links = self.driver.find_elements(By.TAG_NAME, 'a')
            print(f'История {history_num} из {len(hos_links)}')
            # Убираем лишний аргумент cod_input
            hos = self.hos_info(hos_links[0], patient, history_num - 1)
            result = [hos[0], hos[1], len(hos_links)]
            return result
        except Exception as e:
            self.errors.append(
                f'[{time.ctime()} in find_patient_info] [{patient["surname"] + patient["name"] + patient["patronymic"]}] {e}')
            print(e)
            return 0

    def hos_info(self, hos_link, patient, num=0):
        hos_link.click()
        an = self.analyzes(patient, num)
        his = self.history(patient, num)  # пока не реализовано, но можно закомментировать
        return [an, his]

    def history(self, patient, num):
        # Заглушка, чтобы не падало
        return 0

    def analyzes(self, patient, num=0):
        print('Получение анализов...')
        try:
            an_link = self.driver.find_element(By.ID, 'sid28')
            an_link.click()
            time.sleep(1)  # даём время на загрузку таблицы (лучше WebDriverWait)

            rows = self.driver.find_elements(By.XPATH, "//form[@name='analviewform']//table//tr")
            for row in rows:
                tds = row.find_elements(By.TAG_NAME, "td")
                if len(tds) == 5:
                    last_td_text = tds[4].text.strip()
                    # Сравниваем с кодом пациента, преобразуя оба в строки
                    if str(last_td_text) == str(patient['cod']):
                        checkbox = tds[0].find_element(By.TAG_NAME, "input")
                        checkbox.click()

            view_btn = self.driver.find_element(By.XPATH, "//input[@value='Просмотреть отмеченные вместе']")
            view_btn.click()
            time.sleep(1)  # ждём загрузки результатов

            # Преобразуем cod в строку, чтобы избежать ошибки конкатенации
            file_name = (patient['surname'] + patient['name'] + patient['patronymic'] +
                         str(patient['cod']) + '_analyzes_' + str(num) + '.html')
            self.save_to_file(file_name, self.driver.page_source)
            return 1
        except Exception as e:
            self.errors.append(
                f'[{time.ctime()} in analyzes] [{patient["surname"] + patient["name"] + patient["patronymic"] + str(patient["cod"])}] {e}')
            print(e)
            return 0

    
    def go_next(self):
        print('Переход далее...')
        try:
            next_btn = self.driver.find_element(By.XPATH, "//input[@onclick='GoNext()']")
            next_btn.click()
        except Exception as e:
            self.errors.append(f'[{time.ctime()} in nex] {e}')
            print(e)

def load_config(file_name):
        print('Загрузка конфигурации...')
        data = {}
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
        cmd = input('> ').split()
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
            print('Ошибка :',e)

    if shutdown:
        os.system('shutdown /s /t 1')
    driver.quit()


if __name__ == "__main__":
    main()