import csv
import requests
from datetime import datetime, timedelta

class MoyGrafikAPI:
    def __init__(self):
        self.token = 'Bearer NzExZjcxMzA4MzM4MzQ2NmViMWZjZDk3OWJmMjQwNGU0ODBlN2MxM2JlNTdhNjdjZTRlMTk0YWZmOGQyYjdhMg'
        self.base_url = 'https://api.moygrafik.ru/api/external/v1'
        self.headers = {'Authorization': self.token}

    def get_presence_report(self, company_id, start_date, end_date, positions=None):
        url = f"{self.base_url}/reports/presence/{company_id}"
        params = {
            'start_date': start_date,
            'end_date': end_date
        }
        if positions:
            params['positions'] = positions

        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def save_presence_report_to_csv(self, data, filename):
        report_data = []
        placements_data = data.get('placements', {})

        for placement_id, placement in placements_data.items():
            for presence in placement.get('presences', []):
                employee = presence['employee']
                for time_entry in presence.get('time_data', []):
                    report_entry = {
                        'date': time_entry.get('date', ''),
                        'start_time': time_entry.get('start_time', ''),
                        'end_time': time_entry.get('end_time', ''),
                        'is_night_shift': time_entry.get('is_night_shift', False),
                        'original_estimate': time_entry.get('original_estimate', 0),
                        'real_estimate': time_entry.get('real_estimate', 0),
                        'is_red': time_entry.get('is_red', False),
                        'employee_id': employee.get('id', ''),
                        'first_name': employee.get('first_name', ''),
                        'last_name': employee.get('last_name', ''),
                        'email': employee.get('email', '')
                    }
                    report_data.append(report_entry)

        if report_data:
            keys = report_data[0].keys()
            with open(filename, 'w', newline='', encoding='utf-8') as file:
                dict_writer = csv.DictWriter(file, fieldnames=keys)
                dict_writer.writeheader()
                dict_writer.writerows(report_data)
        else:
            print(f"Нет данных для сохранения в {filename}")

# Пример использования
company_id = 1525
api = MoyGrafikAPI()

# Установить начальную и конечную даты
current_date = datetime.now()
start_date = current_date - timedelta(days=10)
end_date = current_date

# Форматируем даты для API
start_date_str = start_date.strftime('%d-%m-%Y')
end_date_str = end_date.strftime('%d-%m-%Y')

print(f"Запрашиваем данные с {start_date_str} по {end_date_str}")

# Получение данных отчёта о присутствии и сохранение в CSV
presence_report = api.get_presence_report(company_id=company_id, start_date=start_date_str, end_date=end_date_str)
api.save_presence_report_to_csv(presence_report, 'presence_report.csv')