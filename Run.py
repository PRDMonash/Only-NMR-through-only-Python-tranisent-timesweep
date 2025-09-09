import os
import csv
import glob
import pandas as pd
import time
import datetime
import threading
import asyncio
import aioserial
from sys import exit
from tqdm import tqdm
from quantiphy import Quantity
from syringe_pump import Pump
from syringe_pump import Manufacturer
from make_a_folder import make_a_folder

# Lock for thread safety 
log_lock = threading.Lock()

# Things that can be CHANGED depending on the experiment and conditions (also conversion calculation furhter on down)
serial = aioserial.AioSerial(port="COM5", baudrate=115200, timeout=2) 
scan_number = 0
tm_number = 0 
tm_increment = 17  # Time between each NMR scan in seconds, set to 17 seconds on benchtop NMR for 1H 
logged_data = []  # List to store logged data

# Legato syringe pump control, need syringe pump module
async def main(flow_rate, run_time): #Sending pump flow rates
    try:
        async with Pump(serial=serial) as pump: 
            await pump.syringe.set_manufacturer(Manufacturer.HAMILTON_GLASS_1000, Quantity("10 ml")) # Set manufacturer, works even if not visible on the pump screen
            await pump.syringe.set_volume(Quantity("20 ml"))
            await pump.infusion_rate.set(Quantity(f"{flow_rate} ml/min")) 
            await pump.run()
            await asyncio.sleep(run_time)  

    except Exception as e:
        print(f"\033[91mSomething went wrong with the pump: {e}\033[0m")

async def stop_pump(): # Separate command to stop
    async with Pump(serial=serial) as pump:
        await pump.stop()

# Create a folder for generated data
project_name, folder_path, YearTime, MonthTime, day = make_a_folder()

# Progress bar with timer to monitor reaction and collect sample during dead time
def countdown(t):
    t = int(round(t))  # Ensure time is an integer
    with tqdm(total=t, bar_format='{l_bar}{bar} | {desc}') as pbar:
        for remaining in range(t, 0, -1):
            mins, secs = divmod(remaining, 60)
            timer_display = f'{mins:02d}:{secs:02d}'
            pbar.set_description(f"\033[1;31mTime left: {timer_display}\033[0m")
            time.sleep(1)
            pbar.update(1)
        pbar.set_description("Time left: 00:00")

# Create an empty CSV file to save calculated data
file_path = os.path.join(folder_path, f'{project_name} analysed.csv')
headers = ['Scan number', 'i0', 'i1', 'Timesweep?', 'tm', 'tres', 'Conversion(%)']
print(f"Creating new CSV file at: {file_path}")

# Open the CSV file and write the headers
with open(file_path, 'w', newline='') as a:
    writer = csv.writer(a)
    writer.writerow(headers)

# Locate the generated NMR data file from benchtop
today = datetime.datetime.now()
exp_path = r"C:\PROJECTS\DATA\{}\{}\{}\SPINSOLVE\??????-RMX-{}".format(YearTime, MonthTime, day, project_name) # Will need changing depending on where data saves
#exp_path = r'C:\Users\SPINSOLVE\Documents\Mia'
#exp_path = r'H:\Documents\Rawdata'
print(f"Looking for files at: {exp_path}")

# Experiment condition inputs
V_reactor = float(input('\033[1;31mPlease input the volume of your reactor (ml):>> \033[0m'))
V_dead = float(input('\033[1;31mPlease input the dead volume of your reactor (ml):>> \033[0m'))
#V_collect = float(input('\033[1;31mPlease input the volume after the NMR (ml):>> \033[0m'))

#print(f'V_reactor is {V_reactor} ml,\nV_dead is {V_dead} ml,\nV_collect is {V_collect} ml')
print(f'V_reactor is {V_reactor} ml,\nV_dead is {V_dead} ml')
i0_vinyl = float(input('\033[1;31mPlease input the number of protons for the vinyl peak (i0):>> \033[0m'))
i1_polymer = float(input('\033[1;31mPlease input the number of protons for the monomer/polymer peak (i1):>> \033[0m'))

# Input the residence time of timesweeps
Timesweep = {}
n = int(input('Please input the number of residence times that will be involved in your reaction:>> '))
if n > 10:
    print("Too many residence times, try again.")
    exit(0) # Most likely adding too many by accident

# Taking each residence time separately
for i in range(n):
    keys = i + 1
    values = float(input('Please input the involved residence time one by one (seconds):>> '))
    Timesweep[keys] = values
print(Timesweep)
time_list = list(Timesweep.values())
print(f'Here is the time list: {time_list}')

# Calculate flow rates
FlowRate_list = [V_reactor * 60 / time for time in time_list]
print(FlowRate_list)

# Calculate sleep time
DeadTime = [V_dead * 60 / flow for flow in FlowRate_list]
SleepTime = [DeadTime[i] + time_list[i] for i in range(n)]
SleepTime[0] = SleepTime[0] * 1.3  # Adjust the first sleep time for stabilisation period

# Work out total volume 
Totalflow = sum(FlowRate_list[i] * SleepTime[i] / 60 for i in range(n))
print(f"The volume needed in this experiment is {Totalflow}")

# Can end here in case need to go back and change things
exp_continue = input("Do you want to continue the experiment? (Y or N)").strip()
if exp_continue.lower() in ['Y', 'y', ' Y', ' y']:
    print("The experiment will start now.")
else:
    exit(0) 

# Function to find i0 and i1 (monomer and polymer integrals) from the NMR 
def collect_integrals(exp_path):
    #Finding and reading the generated NMR file, always a csv file and sorted by the date
    file_type = r"\*.csv"
    files = glob.glob(exp_path + file_type)
    max_file = max(files, key=os.path.getctime)
    nmr_data = pd.read_csv(max_file).dropna()

    # Take last 5 scans
    data = nmr_data.iloc[-1:, :]

    # Attempt to index row based on scan number
    i0 = data.iloc[:, 1].values[0]
    i1 = data.iloc[:, 2].values[0]

    return i0, i1

# Function to collect all the data, work out conversion and tres and log everything
def analyse_data(duration, flow_rate, previous_flow, file_path, exp_path, is_timesweep):
    # Scan number and tm number changed elsewhere
    global scan_number
    global tm_number
    num_steps = int(duration // tm_increment)

    for step in range(num_steps):
        time.sleep(tm_increment)  # Wait for tm_increment seconds

        # Calculate conversion if timesweep
        if is_timesweep == 'Yes':

            # Extract i0 and i1 from the most recent NMR data
            i0, i1 = collect_integrals(exp_path)

            conversion = (1 - ((i0*i1_polymer) / (i1*i0_vinyl))) * 100 # i0 is vinyl, i1 is polymer!!!

            # Calculate residence time for each NMR scan
            tres = (V_reactor / previous_flow) + ((tm_number/60) * (1 - (flow_rate / previous_flow)))

        # If not a timesweep, back to 0
        else:
            i0 = i1 = conversion = tres = None
            tm_number = 0

        # Append a new row to the CSV file every new scan
        with open(file_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([scan_number, i0, i1, is_timesweep, tm_number, tres, conversion])

        # Increment values for the next step
        with log_lock:
            scan_number += 1
            
            if is_timesweep == 'Yes':
                tm_number += tm_increment  # Increment tm number

# Perform the experiment
for i in range(n):
    if i == 0:
        # Stabilisation period for the first flow rate
        print(f"Initial stabilisation, will run for {SleepTime[i]} seconds. Flow rate changed to {FlowRate_list[i]} ml/min.")
        is_timesweep = 'No'  # Timesweep is No during stabilisation
        countdown_thread = threading.Thread(target=countdown, args=(SleepTime[0],))
        countdown_thread.start()  
        log_thread = threading.Thread(target= analyse_data, args=(SleepTime[0], FlowRate_list[i], FlowRate_list[i], file_path, exp_path, is_timesweep))
        log_thread.start()                  
        time.sleep(0.1) # Sleep to allow pump to figure itself out
        asyncio.run(main(FlowRate_list[i], SleepTime[0]))
        countdown_thread.join() 
        log_thread.join()
        # First dead volume
        print(f"Dead volume is emptying now for {DeadTime[i+1]} seconds. Sample can be collected. Flow rate changed to {FlowRate_list[i+1]} ml/min.")
        countdown_thread = threading.Thread(target=countdown, args=(DeadTime[i+1],))
        countdown_thread.start()             
        log_thread = threading.Thread(target= analyse_data, args=(DeadTime[i+1], FlowRate_list[i], FlowRate_list[i], file_path, exp_path, is_timesweep))
        log_thread.start()  
        time.sleep(0.1)
        asyncio.run(stop_pump())
        asyncio.run(main(FlowRate_list[i+1], DeadTime[i+1]))
        countdown_thread.join()                     
        print("Stop collecting sample.") # Dead volume over
        log_thread.join()
    else:
        # Timesweeps start
        print(f'{time_list[i]} seconds residence time starts now')
        is_timesweep = 'Yes'  # Set here before logging thread starts
        countdown_thread = threading.Thread(target=countdown, args=(time_list[i],))
        countdown_thread.start()   
        log_thread = threading.Thread(target= analyse_data, args=(time_list[i], FlowRate_list[i], FlowRate_list[i-1], file_path, exp_path, is_timesweep))
        log_thread.start()    
        time.sleep(0.1)
        asyncio.run(stop_pump())
        asyncio.run(main(FlowRate_list[i], time_list[i]))
        countdown_thread.join()               
        log_thread.join()

        # Start the next flow rate during dead volume between timesweeps, if final timesweep reuse last dead volume time as no change in flow rate
        if i + 1 < n:
            print(f"Dead volume is emptying now for {DeadTime[i+1]} seconds. Sample can be collected. Flow rate changed to {FlowRate_list[i+1]} ml/min")
            is_timesweep = 'No'
            countdown_thread = threading.Thread(target=countdown, args=(DeadTime[i+1],))
            countdown_thread.start()                   
            log_thread = threading.Thread(target= analyse_data, args=(DeadTime[i+1], FlowRate_list[i], FlowRate_list[i-1], file_path, exp_path, is_timesweep))
            log_thread.start()   
            time.sleep(0.1)
            asyncio.run(stop_pump())
            asyncio.run(main(FlowRate_list[i+1], DeadTime[i+1]))
            countdown_thread.join()
            
        else: 
            print(f"Dead volume is emptying now for {DeadTime[i]} seconds. Sample can be collected.")
            is_timesweep = 'No'
            countdown_thread = threading.Thread(target=countdown, args=(DeadTime[i],))
            countdown_thread.start()                  
            log_thread = threading.Thread(target= analyse_data, args=(DeadTime[i], FlowRate_list[i], FlowRate_list[i-1], file_path, exp_path, is_timesweep))
            log_thread.start()   
            time.sleep(0.1)
            asyncio.run(stop_pump())
            asyncio.run(main(FlowRate_list[i], DeadTime[i]))
            countdown_thread.join()

        with log_lock:
            scan_number += 1  # Increment scan number, log_lock to keep global variable safe
            
            if is_timesweep == 'Yes':
                tres = (V_reactor/FlowRate_list[i-1]) + ((tm_number/60) * ( 1 - (FlowRate_list[i]/FlowRate_list[i-1])))
                tm_number_2 = tm_number - tm_increment # Need first timesweep = 'Yes' to be 0, made tnumber_2 just for this
        
            else:
                tres = '' 
                tm_number = 0
                tm_number_2 = 0 
        
        log_thread.join()

        logged_data.append([scan_number, '', '', is_timesweep, tm_number_2, tres])  # Log everything before appending

        # Append information to the calculated file 
        with open(file_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([scan_number, None, None, is_timesweep, tm_number, tres, None])

# Stop the pump
asyncio.run(stop_pump())

# Accounce the finish
print("Finished the experiment!")