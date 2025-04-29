import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta


class MoyGrafikAPI:
    def __init__(self, data_directory):
        # Инициализация токена и базовых URL для API
        self.token = 'Bearer NzExZjcxMzA4MzM4MzQ2NmViMWZjZDk3OWJmMjQwNGU0ODBlN2MxM2JlNTdhNjdjZTRlMTk0YWZmOGQyYjdhMg'
        self.base_url = 'https://api.moygrafik.ru/api/external/v1'
        self.headers = {'Authorization': self.token}


        # Используем указанный путь для сохранения данных
        self.data_dir = Path(data_directory)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def fetch_data(self, endpoint, params=None):
        # Вызов API и получение данных
        response = requests.get(endpoint, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def update_csv(self, file_name, new_data):
        # Определяем путь к файлу CSV
        file_path = self.data_dir / file_name

        # Загрузка существующих данных из CSV файла, если он существует
        if file_path.exists():
            existing_df = pd.read_csv(file_path)
            initial_length = len(existing_df)
        else:
            existing_df = pd.DataFrame()
            initial_length = 0

        # Создание DataFrame из новых данных
        new_df = pd.DataFrame(new_data)

        # Преобразование списков в строковые представления
        for col in new_df.columns:
            if new_df[col].apply(lambda x: isinstance(x, list)).any():
                new_df[col] = new_df[col].apply(lambda x: str(x) if isinstance(x, list) else x)

        # Объединяем существующие и новые данные
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        before_dedup_length = len(combined_df)

        # Удаление дубликатов
        combined_df.drop_duplicates(inplace=True)
        final_length = len(combined_df)

        # Сохраняем обновленный DataFrame в CSV
        combined_df.to_csv(file_path, index=False)

        # Сообщение об обновлении
        print(f"Файл {file_name} обновлен.")
        num_duplicates = before_dedup_length - final_length
        num_new_records = final_length - initial_length
        if num_duplicates > 0:
            print(f"Найдено и удалено {num_duplicates} дубликатов в {file_name}.")
        else:
            print(f"Дубликаты не найдены в {file_name}.")
        print(f"Добавлено {num_new_records} новых уникальных записей в {file_name}.")

    def get_employees(self, company_id):
        url = f"{self.base_url}/companies/{company_id}/employees"
        data = self.fetch_data(url)['employees']

        # Фильтрация по timezone_id
        new_data = [details for details in data.values() if details.get('timezone_id') == 516]
        self.update_csv('employees.csv', new_data)

    def get_presence_report(self, company_id, start_date, end_date):
        url = f"{self.base_url}/reports/presence/{company_id}"
        params = {
            'start_date': start_date.strftime('%d-%m-%Y'),
            'end_date': end_date.strftime('%d-%m-%Y')
        }

        presences = []
        data = self.fetch_data(url, params=params)['placements']
        for placement_id, placement_data in data.items():
            for presence in placement_data.get('presences', []):
                employee = presence['employee']
                if employee.get('timezone_id') == 516:  # Фильтрация по timezone_id 516
                    for time_entry in presence.get('time_data', []):
                        time_entry['employee_id'] = employee['id']
                        time_entry['first_name'] = employee['first_name']
                        time_entry['last_name'] = employee['last_name']
                        time_entry['email'] = employee.get('email')
                        presences.append(time_entry)
        self.update_csv('presence_report.csv', presences)

    def get_placements(self, company_id):
        url = f"{self.base_url}/companies/{company_id}/placements"
        data = self.fetch_data(url)['placements']
        new_data = list(data.values())
        self.update_csv('placements.csv', new_data)

    def get_subdivisions(self, company_id):
        url = f"{self.base_url}/companies/{company_id}/subdivisions"
        data = self.fetch_data(url)['subdivisions']
        new_data = list(data.values())
        self.update_csv('subdivisions.csv', new_data)

    def get_positions(self, company_id):
        url = f"{self.base_url}/companies/{company_id}/positions"
        data = self.fetch_data(url)['positions']
        new_data = list(data.values())
        self.update_csv('positions.csv', new_data)

    def record_last_run(self):
        last_run_file = self.data_dir / "last_run.txt"
        with open(last_run_file, 'w') as f:
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"Последний запуск: {current_time}")
        print(f"Время последнего запуска записано: {current_time}")


# Пример использования
data_path = "/Users/shish.me/PycharmProjects/MoyGrafik_bot_01/database"  # Укажите ваш путь здесь
api = MoyGrafikAPI(data_path)
company_id = 1525

# Обновляем данные сотрудников, размещений, подразделений и позиций
api.get_employees(company_id=company_id)

# Определяем начальную дату за 11 дней до текущей для 10-дневного шага
current_date = datetime.now()
start_date = current_date - timedelta(days=11)

# Получаем данные о присутствии с шагом в 10 дней
while start_date < current_date:
    end_date = start_date + timedelta(days=9)
    if end_date > current_date:
        end_date = current_date
    api.get_presence_report(company_id=company_id, start_date=start_date, end_date=end_date)
    start_date += timedelta(days=10)

# Записываем время последнего запуска
api.record_last_run()

# Загрузим и выведем каждый DataFrame
employees_df = pd.read_csv(api.data_dir / 'employees.csv')
placements_df = pd.read_csv(api.data_dir / 'placements.csv')
subdivisions_df = pd.read_csv(api.data_dir / 'subdivisions.csv')
positions_df = pd.read_csv(api.data_dir / 'positions.csv')
presence_report_df = pd.read_csv(api.data_dir / 'presence_report.csv')

print("Employees:")
print(employees_df)
print("\nPlacements:")
print(placements_df)
print("\nSubdivisions:")
print(subdivisions_df)
print("\nPositions:")
print(positions_df)
print("\nPresence Report:")
print(presence_report_df)