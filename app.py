import streamlit as st
import pandas as pd
from datetime import datetime, time
import calendar
from io import BytesIO
import json
import os

# --- Logic Functions ---

CONFIG_FILE = "salary_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"teacher_rate": 25.0, "admin_rates": {}}

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

def get_workdays(year, month):
    """Returns total number of weekdays (Mon-Fri) in the given month"""
    cal = calendar.monthcalendar(year, month)
    workdays = 0
    for week in cal:
        for i in range(5):
            if week[i] != 0:
                workdays += 1
    return workdays

def get_custom_workdays(year, month, working_days_list):
    """Returns total number of configured working days in the given month"""
    cal = calendar.monthcalendar(year, month)
    workdays = 0
    for week in cal:
        for day_idx in working_days_list:
            if week[day_idx] != 0:
                workdays += 1
    return workdays

def process_attendance(df_raw, admin_rates, admin_working_days, teacher_rate, teacher_quotas, hybrid_custom_hours, start_date, end_date):
    df = df_raw.copy()
    df.columns = df.columns.str.strip()
    
    required_cols = ['Staff Name', 'Department', 'Date Time', 'Status']
    for col in required_cols:
        if col not in df.columns:
            return None, None, None, None, f"ფაილი არ შეიცავს სავალდებულო სვეტს: {col}"
            
    try:
        df['Date Time'] = pd.to_datetime(df['Date Time'])
    except Exception as e:
        return None, None, None, None, f"თარიღის ფორმატი არასწორია: {e}"
        
    df = df[(df['Date Time'].dt.date >= start_date) & (df['Date Time'].dt.date <= end_date)].copy()
    
    # Preserve existing calculation base by strictly using the start date month
    selected_year = start_date.year
    selected_month = start_date.month
    
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "არჩეული თვისთვის მონაცემები არ მოიძებნა."
        
    df['Date'] = df['Date Time'].dt.date
    df['Time'] = df['Date Time'].dt.time
    # Get ISO week for weekly grouping
    df['Week'] = df['Date Time'].dt.isocalendar().week
    
    df = df.sort_values(by=['Staff Name', 'Date Time'])
    
    daily_data = []
    errors_data = []
    
    for emp_name, emp_df in df.groupby('Staff Name'):
        emp_dept = str(emp_df['Department'].iloc[0]).strip()
        
        if emp_dept == 'ადმინისტრაცია':
            monthly_salary = admin_rates.get(emp_name, 0.0)
            emp_working_days = admin_working_days.get(emp_name, [0, 1, 2, 3, 4])
            total_workdays = get_custom_workdays(selected_year, selected_month, emp_working_days)
            max_daily_rate = monthly_salary / total_workdays if total_workdays > 0 else 0.0
            
            for date, day_df in emp_df.groupby('Date'):
                week_num = day_df['Week'].iloc[0]
                check_ins = day_df[day_df['Status'].str.strip().str.lower() == 'check in']
                check_outs = day_df[day_df['Status'].str.strip().str.lower() == 'check out']
                
                is_working_day = date.weekday() in emp_working_days
                
                if len(day_df) % 2 != 0 or check_ins.empty or check_outs.empty:
                    errors_data.append({
                        "თანამშრომელი": emp_name,
                        "თარიღი": date,
                        "პრობლემა": "ნაკლული ან არასწორი გატარება (დღე იგნორირებულია)"
                    })
                    daily_data.append({
                        "თანამშრომელი": emp_name,
                        "დეპარტამენტი": emp_dept,
                        "თარიღი": date,
                        "კვირა": week_num,
                        "ნამუშევარი საათები": 0.0,
                        "ზეგანაკვეთური საათები": 0.0,
                        "დეფიციტური საათები": 6.0 if is_working_day else 0.0,
                        "გამომუშავებული ხელფასი": 0.0
                    })
                    continue
                    
                first_in = check_ins['Date Time'].min()
                last_out = check_outs['Date Time'].max()
                
                if last_out > first_in:
                    worked_hours = (last_out - first_in).total_seconds() / 3600.0
                    
                    if not is_working_day:
                        deficit_hours = 0.0
                        extra_hours = 0.0
                        daily_salary = 0.0
                    else:
                        standard_start = first_in.replace(hour=10, minute=0, second=0, microsecond=0)
                        standard_end = first_in.replace(hour=16, minute=0, second=0, microsecond=0)
                        
                        actual_start = max(first_in, standard_start)
                        actual_end = min(last_out, standard_end)
                        
                        if actual_end > actual_start:
                            standard_worked_hours = (actual_end - actual_start).total_seconds() / 3600.0
                        else:
                            standard_worked_hours = 0.0
                            
                        deficit_hours = max(0.0, 6.0 - standard_worked_hours)
                        
                        if last_out > standard_end:
                            extra_hours = (last_out - standard_end).total_seconds() / 3600.0
                        else:
                            extra_hours = 0.0
                        
                        daily_salary = (standard_worked_hours / 6.0) * max_daily_rate
                else:
                    errors_data.append({
                        "თანამშრომელი": emp_name,
                        "თარიღი": date,
                        "პრობლემა": "Check Out დრო Check In დროზე ადრეა (დღე იგნორირებულია)"
                    })
                    daily_data.append({
                        "თანამშრომელი": emp_name,
                        "დეპარტამენტი": emp_dept,
                        "თარიღი": date,
                        "კვირა": week_num,
                        "ნამუშევარი საათები": 0.0,
                        "ზეგანაკვეთური საათები": 0.0,
                        "დეფიციტური საათები": 6.0 if is_working_day else 0.0,
                        "გამომუშავებული ხელფასი": 0.0
                    })
                    continue
                    
                daily_data.append({
                    "თანამშრომელი": emp_name,
                    "დეპარტამენტი": emp_dept,
                    "თარიღი": date,
                    "კვირა": week_num,
                    "ნამუშევარი საათები": worked_hours,
                    "ზეგანაკვეთური საათები": extra_hours,
                    "დეფიციტური საათები": deficit_hours,
                    "გამომუშავებული ხელფასი": daily_salary
                })
                
        elif emp_dept == 'მასწავლებელი':
            for date, day_df in emp_df.groupby('Date'):
                week_num = day_df['Week'].iloc[0]
                check_ins = day_df[day_df['Status'].str.strip().str.lower() == 'check in']
                check_outs = day_df[day_df['Status'].str.strip().str.lower() == 'check out']
                
                if len(day_df) % 2 != 0 or check_ins.empty or check_outs.empty:
                    errors_data.append({
                        "თანამშრომელი": emp_name,
                        "თარიღი": date,
                        "პრობლემა": "ნაკლული ან არასწორი გატარება (დღე იგნორირებულია)"
                    })
                    daily_data.append({
                        "თანამშრომელი": emp_name,
                        "დეპარტამენტი": emp_dept,
                        "თარიღი": date,
                        "კვირა": week_num,
                        "ნამუშევარი საათები": 0.0,
                        "ზეგანაკვეთური საათები": 0.0,
                        "დეფიციტური საათები": 0.0,
                        "გამომუშავებული ხელფასი": 0.0
                    })
                    continue
                    
                if last_out > first_in:
                    worked_hours = (last_out - first_in).total_seconds() / 3600.0
                    extra_hours = 0.0
                    deficit_hours = 0.0
                    daily_salary = worked_hours * teacher_rate
                else:
                    errors_data.append({
                        "თანამშრომელი": emp_name,
                        "თარიღი": date,
                        "პრობლემა": "Check Out დრო Check In დროზე ადრეა (დღე იგნორირებულია)"
                    })
                    daily_data.append({
                        "თანამშრომელი": emp_name,
                        "დეპარტამენტი": emp_dept,
                        "თარიღი": date,
                        "კვირა": week_num,
                        "ნამუშევარი საათები": 0.0,
                        "ზეგანაკვეთური საათები": 0.0,
                        "დეფიციტური საათები": 0.0,
                        "გამომუშავებული ხელფასი": 0.0
                    })
                    continue
                    
                daily_data.append({
                    "თანამშრომელი": emp_name,
                    "დეპარტამენტი": emp_dept,
                    "თარიღი": date,
                    "კვირა": week_num,
                    "ნამუშევარი საათები": worked_hours,
                    "ზეგანაკვეთური საათები": extra_hours,
                    "დეფიციტური საათები": deficit_hours,
                    "გამომუშავებული ხელფასი": daily_salary
                })
                
        elif emp_dept == 'ადმნისტრაცია და მასწავლებელი':
            monthly_salary = admin_rates.get(emp_name, 0.0)
            emp_working_days = admin_working_days.get(emp_name, [0, 1, 2, 3, 4])
            total_workdays = get_custom_workdays(selected_year, selected_month, emp_working_days)
            max_daily_rate = monthly_salary / total_workdays if total_workdays > 0 else 0.0
            
            for date, day_df in emp_df.groupby('Date'):
                week_num = day_df['Week'].iloc[0]
                check_ins = day_df[day_df['Status'].str.strip().str.lower() == 'check in']
                check_outs = day_df[day_df['Status'].str.strip().str.lower() == 'check out']
                
                is_working_day = date.weekday() in emp_working_days
                
                if len(day_df) % 2 != 0 or check_ins.empty or check_outs.empty:
                    errors_data.append({
                        "თანამშრომელი": emp_name,
                        "თარიღი": date,
                        "პრობლემა": "ნაკლული ან არასწორი გატარება (დღე იგნორირებულია)"
                    })
                    daily_data.append({
                        "თანამშრომელი": emp_name,
                        "დეპარტამენტი": emp_dept,
                        "თარიღი": date,
                        "კვირა": week_num,
                        "ნამუშევარი საათები": 0.0,
                        "ზეგანაკვეთური საათები": 0.0,
                        "დეფიციტური საათები": 6.0 if is_working_day else 0.0,
                        "გამომუშავებული ხელფასი": 0.0
                    })
                    continue
                    
                first_in = check_ins['Date Time'].min()
                last_out = check_outs['Date Time'].max()
                
                if last_out > first_in:
                    worked_hours = (last_out - first_in).total_seconds() / 3600.0
                    
                    if not is_working_day:
                        deficit_hours = 0.0
                        extra_hours = 0.0
                        daily_salary = 0.0
                    else:
                        standard_start = first_in.replace(hour=10, minute=0, second=0, microsecond=0)
                        standard_end = first_in.replace(hour=16, minute=0, second=0, microsecond=0)
                        
                        actual_start = max(first_in, standard_start)
                        actual_end = min(last_out, standard_end)
                        
                        if actual_end > actual_start:
                            standard_worked_hours = (actual_end - actual_start).total_seconds() / 3600.0
                        else:
                            standard_worked_hours = 0.0
                            
                        deficit_hours = max(0.0, 6.0 - standard_worked_hours)
                        
                        if last_out > standard_end:
                            extra_hours = (last_out - standard_end).total_seconds() / 3600.0
                        else:
                            extra_hours = 0.0
                        
                        daily_salary = (standard_worked_hours / 6.0) * max_daily_rate
                else:
                    errors_data.append({
                        "თანამშრომელი": emp_name,
                        "თარიღი": date,
                        "პრობლემა": "Check Out დრო Check In დროზე ადრეა (დღე იგნორირებულია)"
                    })
                    daily_data.append({
                        "თანამშრომელი": emp_name,
                        "დეპარტამენტი": emp_dept,
                        "თარიღი": date,
                        "კვირა": week_num,
                        "ნამუშევარი საათები": 0.0,
                        "ზეგანაკვეთური საათები": 0.0,
                        "დეფიციტური საათები": 6.0 if is_working_day else 0.0,
                        "გამომუშავებული ხელფასი": 0.0
                    })
                    continue
                    
                daily_data.append({
                    "თანამშრომელი": emp_name,
                    "დეპარტამენტი": emp_dept,
                    "თარიღი": date,
                    "კვირა": week_num,
                    "ნამუშევარი საათები": worked_hours,
                    "ზეგანაკვეთური საათები": extra_hours,
                    "დეფიციტური საათები": deficit_hours,
                    "გამომუშავებული ხელფასი": daily_salary
                })
                
    df_daily = pd.DataFrame(daily_data)
    df_errors = pd.DataFrame(errors_data)
    
    if df_daily.empty:
        return df_daily, pd.DataFrame(), pd.DataFrame(), df_errors, None
        
    # Generate Weekly
    df_weekly = df_daily.groupby(['თანამშრომელი', 'დეპარტამენტი', 'კვირა']).agg({
        'ნამუშევარი საათები': 'sum',
        'ზეგანაკვეთური საათები': 'sum',
        'დეფიციტური საათები': 'sum',
        'გამომუშავებული ხელფასი': 'sum'
    }).reset_index()
    
    # Generate Monthly
    df_monthly = df_daily.groupby(['თანამშრომელი', 'დეპარტამენტი']).agg({
        'ნამუშევარი საათები': 'sum',
        'ზეგანაკვეთური საათები': 'sum',
        'დეფიციტური საათები': 'sum',
        'გამომუშავებული ხელფასი': 'sum'
    }).reset_index()
    
    # Map teacher quotas
    def map_quota(row):
        if row['დეპარტამენტი'] == 'მასწავლებელი':
            return teacher_quotas.get(row['თანამშრომელი'], 0.0)
        return 0.0
        
    df_monthly.insert(2, 'ყოველთვიური სავალდებულო საათები', df_monthly.apply(map_quota, axis=1))
    
    # Recalculate Teacher Monthly Metrics (Capping & Deficit)
    for idx, row in df_monthly.iterrows():
        if row['დეპარტამენტი'] == 'მასწავლებელი':
            total_worked = row['ნამუშევარი საათები']
            monthly_req = row['ყოველთვიური სავალდებულო საათები']
            
            if monthly_req > 0:
                final_salary = min(total_worked, monthly_req) * teacher_rate
                deficit = max(0.0, monthly_req - total_worked)
                extra = max(0.0, total_worked - monthly_req)
            else:
                final_salary = total_worked * teacher_rate
                deficit = 0.0
                extra = 0.0
                
            df_monthly.at[idx, 'გამომუშავებული ხელფასი'] = final_salary
            df_monthly.at[idx, 'დეფიციტური საათები'] = deficit
            df_monthly.at[idx, 'ზეგანაკვეთური საათები'] = extra
            
        elif row['დეპარტამენტი'] == 'ადმნისტრაცია და მასწავლებელი':
            emp_name = row['თანამშრომელი']
            
            # Step A: Admin Salary Component
            monthly_salary = admin_rates.get(emp_name, 0.0)
            total_deficit = row['დეფიციტური საათები']
            
            emp_working_days = admin_working_days.get(emp_name, [0, 1, 2, 3, 4])
            total_workdays = get_custom_workdays(selected_year, selected_month, emp_working_days)
            max_daily_rate = monthly_salary / total_workdays if total_workdays > 0 else 0.0
            hourly_deduction_rate = max_daily_rate / 6.0 if max_daily_rate > 0 else 0.0
            
            total_deduction = total_deficit * hourly_deduction_rate
            net_admin_salary = max(0.0, monthly_salary - total_deduction)
            
            # Step B: Teacher Salary Component
            manual_hours = hybrid_custom_hours.get(emp_name, 0.0)
            teaching_salary = manual_hours * teacher_rate
            
            # Step C: Final Sum
            final_salary = net_admin_salary + teaching_salary
            
            df_monthly.at[idx, 'გამომუშავებული ხელფასი'] = final_salary
            # Leaving deficit_hours and extra_hours intact because they reflect Admin metrics
            # Keeping the raw total_worked inside 'ნამუშევარი საათები' for transparency
    
    # Round metrics for all
    for d in [df_daily, df_weekly, df_monthly]:
        d['ნამუშევარი საათები'] = d['ნამუშევარი საათები'].round(2)
        d['ზეგანაკვეთური საათები'] = d['ზეგანაკვეთური საათები'].round(2)
        d['დეფიციტური საათები'] = d['დეფიციტური საათები'].round(2)
        d['გამომუშავებული ხელფასი'] = d['გამომუშავებული ხელფასი'].round(2)
        
    return df_daily, df_weekly, df_monthly, df_errors, None

def export_to_excel(df_daily, df_weekly, df_monthly, df_errors):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if not df_monthly.empty:
            df_monthly.to_excel(writer, sheet_name='თვიური_შეჯამება', index=False)
        if not df_weekly.empty:
            df_weekly.to_excel(writer, sheet_name='კვირეული_შეჯამება', index=False)
        if not df_daily.empty:
            df_daily.to_excel(writer, sheet_name='დღიური_რეპორტი', index=False)
        if not df_errors.empty:
            df_errors.to_excel(writer, sheet_name='შეცდომები', index=False)
    return output.getvalue()

# --- Streamlit UI ---

if 'config' not in st.session_state:
    st.session_state.config = load_config()

st.set_page_config(page_title="ხელფასების კალკულატორი", page_icon="💰", layout="wide")

st.title("სახელფასო სისტემა")

st.sidebar.header("პერიოდი")
date_range = st.sidebar.date_input(
    "აირჩიეთ პერიოდი (თარიღიდან - თარიღამდე)",
    value=(datetime.now().replace(day=1).date(), datetime.now().date()),
    max_value=datetime(2100, 12, 31).date()
)

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    st.sidebar.warning("გთხოვთ აირჩიოთ საწყისი და საბოლოო თარიღი.")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.header("პარამეტრები")

def update_teacher_config():
    st.session_state.config['teacher_rate'] = st.session_state.teacher_rate_input
    save_config(st.session_state.config)

teacher_rate = st.sidebar.number_input(
    "მასწავლებლის საათობრივი ანაზღაურება", 
    min_value=0.0, 
    value=float(st.session_state.config.get('teacher_rate', 25.0)), 
    step=1.0,
    key='teacher_rate_input',
    on_change=update_teacher_config
)

st.subheader("1. ფაილის ატვირთვა")
uploaded_file = st.file_uploader("ატვირთეთ მონაცემთა ფაილი (Excel / CSV)", type=['csv', 'xlsx'])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file)
        else:
            df_raw = pd.read_excel(uploaded_file)
            
        df_raw.columns = df_raw.columns.str.strip()
        
        if 'Staff Name' in df_raw.columns and 'Department' in df_raw.columns:
            
            # CRITICAL DATA CLEANING
            df_raw['Staff Name'] = df_raw['Staff Name'].replace(['N/A', 'NaN', 'nan', 'None'], pd.NA)
            df_raw = df_raw.dropna(subset=['Staff Name'])
            df_raw['Staff Name'] = df_raw['Staff Name'].astype(str)
            df_raw = df_raw[df_raw['Staff Name'].str.strip() != '']
            
            df_raw = df_raw.drop(columns=['ID'], errors='ignore')
            
            # Extract Admins for configuration
            admins_raw = df_raw[df_raw['Department'].str.strip() == 'ადმინისტრაცია']
            
            if not admins_raw.empty:
                emp_df = admins_raw[['Staff Name']].drop_duplicates(subset=['Staff Name']).copy()
                
                saved_admin_rates = st.session_state.config.get('admin_rates', {})
                saved_admin_days = st.session_state.config.get('admin_working_days', {})
                
                days_map = {0: "ორშაბათი", 1: "სამშაბათი", 2: "ოთხშაბათი", 3: "ხუთშაბათი", 4: "პარასკევი", 5: "შაბათი", 6: "კვირა"}
                
                for _, row in emp_df.iterrows():
                    staff_name = row['Staff Name']
                    if staff_name not in saved_admin_rates:
                        saved_admin_rates[staff_name] = 0.0
                    if staff_name not in saved_admin_days:
                        saved_admin_days[staff_name] = [0, 1, 2, 3, 4]
                        
                st.session_state.config['admin_rates'] = saved_admin_rates
                st.session_state.config['admin_working_days'] = saved_admin_days
                
                emp_df['ფიქსირებული თვიური ხელფასი'] = emp_df['Staff Name'].map(st.session_state.config['admin_rates'])
                for i, day_name in days_map.items():
                    emp_df[day_name] = emp_df['Staff Name'].apply(lambda x: i in st.session_state.config['admin_working_days'].get(x, []))
                
                st.markdown("---")
                st.subheader("2. ადმინისტრაციის კონფიგურაცია")
                st.write("შეიყვანეთ ინდივიდუალური ფიქსირებული თვიური ხელფასი და მონიშნეთ სამუშაო დღეები ადმინისტრაციის თითოეული წევრისთვის.")
                
                col_config = {
                    "ფიქსირებული თვიური ხელფასი": st.column_config.NumberColumn(
                        "ფიქსირებული თვიური ხელფასი", min_value=0.0, step=50.0, format="%.2f"
                    )
                }
                for day_name in days_map.values():
                    col_config[day_name] = st.column_config.CheckboxColumn(day_name)
                
                edited_emp_df = st.data_editor(
                    emp_df,
                    hide_index=True,
                    disabled=["Staff Name"],
                    column_config=col_config,
                    use_container_width=True
                )
                
                config_changed = False
                for idx, row in edited_emp_df.iterrows():
                    staff_name = row['Staff Name']
                    
                    if st.session_state.config['admin_rates'].get(staff_name) != row['ფიქსირებული თვიური ხელფასი']:
                        st.session_state.config['admin_rates'][staff_name] = row['ფიქსირებული თვიური ხელფასი']
                        config_changed = True
                        
                    selected_days = [i for i, day_name in days_map.items() if row[day_name]]
                    if st.session_state.config['admin_working_days'].get(staff_name) != selected_days:
                        st.session_state.config['admin_working_days'][staff_name] = selected_days
                        config_changed = True
                        
                if config_changed:
                    save_config(st.session_state.config)
            else:
                st.info("ფაილში ადმინისტრაციის თანამშრომლები არ მოიძებნა.")
                
            # Extract Teachers for configuration
            teachers_raw = df_raw[df_raw['Department'].str.strip() == 'მასწავლებელი']
            
            if not teachers_raw.empty:
                t_df = teachers_raw[['Staff Name']].drop_duplicates(subset=['Staff Name']).copy()
                
                saved_teacher_quotas = st.session_state.config.get('teacher_quotas', {})
                
                for _, row in t_df.iterrows():
                    staff_name = row['Staff Name']
                    if staff_name not in saved_teacher_quotas:
                        saved_teacher_quotas[staff_name] = 120.0
                        
                st.session_state.config['teacher_quotas'] = saved_teacher_quotas
                
                t_df['ყოველთვიური სავალდებულო საათები'] = t_df['Staff Name'].map(st.session_state.config['teacher_quotas'])
                
                st.markdown("---")
                st.subheader("3. მასწავლებლების კონფიგურაცია")
                st.write("შეიყვანეთ ინდივიდუალური ყოველთვიური სავალდებულო საათები.")
                
                edited_t_df = st.data_editor(
                    t_df,
                    hide_index=True,
                    disabled=["Staff Name"],
                    column_config={
                        "ყოველთვიური სავალდებულო საათები": st.column_config.NumberColumn(
                            "ყოველთვიური სავალდებულო საათები",
                            min_value=0.0,
                            step=1.0,
                            format="%.2f"
                        )
                    },
                    use_container_width=True
                )
                
                edited_teacher_quotas_dict = dict(zip(edited_t_df['Staff Name'], edited_t_df['ყოველთვიური სავალდებულო საათები']))
                config_changed = False
                for k, v in edited_teacher_quotas_dict.items():
                    if st.session_state.config['teacher_quotas'].get(k) != v:
                        st.session_state.config['teacher_quotas'][k] = v
                        config_changed = True
                if config_changed:
                    save_config(st.session_state.config)
            else:
                st.info("ფაილში მასწავლებლები არ მოიძებნა.")
                
            # Extract Hybrid for configuration
            hybrid_raw = df_raw[df_raw['Department'].str.strip() == 'ადმნისტრაცია და მასწავლებელი']
            
            if not hybrid_raw.empty:
                h_df = hybrid_raw[['Staff Name']].drop_duplicates(subset=['Staff Name']).copy()
                
                saved_admin_rates = st.session_state.config.get('admin_rates', {})
                saved_hybrid_hours = st.session_state.config.get('hybrid_custom_hours', {})
                saved_admin_days = st.session_state.config.get('admin_working_days', {})
                
                days_map = {0: "ორშაბათი", 1: "სამშაბათი", 2: "ოთხშაბათი", 3: "ხუთშაბათი", 4: "პარასკევი", 5: "შაბათი", 6: "კვირა"}
                
                for _, row in h_df.iterrows():
                    staff_name = row['Staff Name']
                    if staff_name not in saved_admin_rates:
                        saved_admin_rates[staff_name] = 0.0
                    if staff_name not in saved_hybrid_hours:
                        saved_hybrid_hours[staff_name] = 0.0
                    if staff_name not in saved_admin_days:
                        saved_admin_days[staff_name] = [0, 1, 2, 3, 4]
                        
                st.session_state.config['admin_rates'] = saved_admin_rates
                st.session_state.config['hybrid_custom_hours'] = saved_hybrid_hours
                st.session_state.config['admin_working_days'] = saved_admin_days
                
                h_df['ფიქსირებული თვიური ხელფასი'] = h_df['Staff Name'].map(st.session_state.config['admin_rates'])
                h_df['დამატებითი საათები'] = h_df['Staff Name'].map(st.session_state.config['hybrid_custom_hours'])
                for i, day_name in days_map.items():
                    h_df[day_name] = h_df['Staff Name'].apply(lambda x: i in st.session_state.config['admin_working_days'].get(x, []))
                
                st.markdown("---")
                st.subheader("4. ჰიბრიდული თანამშრომლების კონფიგურაცია")
                st.write("შეიყვანეთ ფიქსირებული ხელფასი, დამატებითი საათები და მონიშნეთ სამუშაო დღეები ჰიბრიდული თანამშრომლებისთვის.")
                
                col_config = {
                    "ფიქსირებული თვიური ხელფასი": st.column_config.NumberColumn(
                        "ფიქსირებული თვიური ხელფასი", min_value=0.0, step=50.0, format="%.2f"
                    ),
                    "დამატებითი საათები": st.column_config.NumberColumn(
                        "დამატებითი საათები", min_value=0.0, step=1.0, format="%.2f"
                    )
                }
                for day_name in days_map.values():
                    col_config[day_name] = st.column_config.CheckboxColumn(day_name)
                    
                edited_h_df = st.data_editor(
                    h_df,
                    hide_index=True,
                    disabled=["Staff Name"],
                    column_config=col_config,
                    use_container_width=True
                )
                
                config_changed = False
                for idx, row in edited_h_df.iterrows():
                    staff_name = row['Staff Name']
                    
                    if st.session_state.config['admin_rates'].get(staff_name) != row['ფიქსირებული თვიური ხელფასი']:
                        st.session_state.config['admin_rates'][staff_name] = row['ფიქსირებული თვიური ხელფასი']
                        config_changed = True
                        
                    if st.session_state.config['hybrid_custom_hours'].get(staff_name) != row['დამატებითი საათები']:
                        st.session_state.config['hybrid_custom_hours'][staff_name] = row['დამატებითი საათები']
                        config_changed = True
                        
                    selected_days = [i for i, day_name in days_map.items() if row[day_name]]
                    if st.session_state.config['admin_working_days'].get(staff_name) != selected_days:
                        st.session_state.config['admin_working_days'][staff_name] = selected_days
                        config_changed = True
                        
                if config_changed:
                    save_config(st.session_state.config)
            else:
                st.info("ფაილში ჰიბრიდული თანამშრომლები არ მოიძებნა.")
            
            st.markdown("---")
            st.subheader("5. მონაცემების დათვლა და რეპორტი")
            
            # Department Filter
            filter_options = ["ყველა", "ადმინისტრაცია", "მასწავლებელი"]
            selected_filter = st.radio("ფილტრი:", filter_options, horizontal=True)
            
            if st.button("სახელფასო უწყისის გენერირება"):
                with st.spinner("მიმდინარეობს მონაცემების დამუშავება..."):
                    final_admin_rates = st.session_state.config.get('admin_rates', {})
                    final_admin_days = st.session_state.config.get('admin_working_days', {})
                    final_teacher_quotas = st.session_state.config.get('teacher_quotas', {})
                    final_hybrid_hours = st.session_state.config.get('hybrid_custom_hours', {})
                    
                    df_daily, df_weekly, df_monthly, df_errors, error_msg = process_attendance(
                        df_raw, final_admin_rates, final_admin_days, teacher_rate, final_teacher_quotas, final_hybrid_hours, start_date, end_date
                    )
                    
                    if error_msg:
                        st.error(error_msg)
                    else:
                        st.success("დათვლა წარმატებით დასრულდა!")
                        
                        # Apply Department Filter
                        if selected_filter != "ყველა":
                            if selected_filter == "ადმინისტრაცია":
                                allowed_depts = ["ადმინისტრაცია", "ადმნისტრაცია და მასწავლებელი"]
                            elif selected_filter == "მასწავლებელი":
                                allowed_depts = ["მასწავლებელი", "ადმნისტრაცია და მასწავლებელი"]
                            else:
                                allowed_depts = [selected_filter]
                                
                            if not df_daily.empty: df_daily = df_daily[df_daily['დეპარტამენტი'].str.strip().isin(allowed_depts)]
                            if not df_weekly.empty: df_weekly = df_weekly[df_weekly['დეპარტამენტი'].str.strip().isin(allowed_depts)]
                            if not df_monthly.empty: df_monthly = df_monthly[df_monthly['დეპარტამენტი'].str.strip().isin(allowed_depts)]
                            if not df_errors.empty: 
                                emp_dept_map = df_raw.drop_duplicates(subset=['Staff Name']).set_index('Staff Name')['Department'].str.strip().to_dict()
                                df_errors['დეპარტამენტი'] = df_errors['თანამშრომელი'].map(emp_dept_map)
                                df_errors = df_errors[df_errors['დეპარტამენტი'].isin(allowed_depts)]
                                df_errors = df_errors.drop(columns=['დეპარტამენტი'])
                        
                        tab1, tab2, tab3, tab4 = st.tabs(["თვიური (Monthly)", "კვირეული (Weekly)", "დღიური (Daily)", "შეცდომები (Errors)"])
                        
                        with tab1:
                            if not df_monthly.empty:
                                st.dataframe(df_monthly, use_container_width=True, hide_index=True)
                            else:
                                st.info("თვიური მონაცემები არ არის.")
                                
                        with tab2:
                            if not df_weekly.empty:
                                st.dataframe(df_weekly, use_container_width=True, hide_index=True)
                            else:
                                st.info("კვირეული მონაცემები არ არის.")
                                
                        with tab3:
                            if not df_daily.empty:
                                st.dataframe(df_daily, use_container_width=True, hide_index=True)
                            else:
                                st.info("დღიური მონაცემები არ არის.")
                                
                        with tab4:
                            if not df_errors.empty:
                                st.dataframe(df_errors, use_container_width=True, hide_index=True)
                            else:
                                st.success("შეცდომები არ მოიძებნა.")
                                
                        if not df_monthly.empty or not df_errors.empty:
                            excel_data = export_to_excel(df_daily, df_weekly, df_monthly, df_errors)
                            st.download_button(
                                label="📥 ყველა ცხრილის Excel-ში ჩამოტვირთვა",
                                data=excel_data,
                                file_name=f"payroll_report_{start_date}_to_{end_date}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                            
        else:
            st.error("ფაილი არ შეიცავს 'Staff Name', ან 'Department' სვეტებს.")
            
    except Exception as e:
        st.error(f"ფაილის წაკითხვისას დაფიქსირდა შეცდომა: {str(e)}")

else:
    st.info("გთხოვთ ატვირთოთ ფაილი, რათა გააგრძელოთ.")
