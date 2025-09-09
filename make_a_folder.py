import os
import datetime

def make_a_folder():
    """
    Creates a folder structure based on the current date and user-provided project name.
    """
    today = datetime.datetime.now()
    year, month, day = today.strftime("%Y"), today.strftime("%m"), today.strftime("%d")
    print(f"Date: {year}/{month}/{day}")

    # Specify the path for the directory
    parent_path = r'C:\Users\SPINSOLVE\Documents\Mia\Calculated_data'
    #parent_path =r'H:\Documents\Calculateddata'

    # Get the project name from the user
    project_name = input("Name of the exp: ").strip()

    if not project_name:
        print("Project name cannot be empty. Exiting.")

    # Create the folder structure
    folder_path = os.path.join(parent_path, year, month, day, project_name)
    os.makedirs(folder_path, exist_ok=True)

    print(f"Folder structure created: {folder_path}")
    return project_name, folder_path, year, month, day