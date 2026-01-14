import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def scrape_chp_cad():
    # Setup Chrome options (headless mode optional)
    chrome_options = Options()
    # chrome_options.add_argument("--headless") # Uncomment to run without a window
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wait = WebDriverWait(driver, 15)

    try:
        driver.get("https://cad.chp.ca.gov/")

        # 1. Select a Communications Center (e.g., 'Sacramento')
        # Wait for the dropdown to be present
        center_dropdown = wait.until(EC.presence_of_element_located((By.ID, "ddlComCenter")))
        select_center = Select(center_dropdown)
        
        print("Selecting Communications Center...")
        # You can change 'Sacramento' to any center name visible in the dropdown
        select_center.select_by_visible_text("Los Angeles")

        # 2. Wait for the data table to load
        # The site uses a table with ID 'gvIncidents' to display results
        print("Waiting for incident data...")
        time.sleep(3) # Give it a moment to trigger the postback

        # Check if the table exists
        try:
            table = wait.until(EC.presence_of_element_located((By.ID, "gvIncidents")))
            rows = table.find_elements(By.TAG_NAME, "tr")

            # 3. Parse the data
            data = []
            for row in rows[1:]:  # Skip the header row
                cols = row.find_elements(By.TAG_NAME, "td")
                for col in cols:
                    col_text = col.text.strip()
                    print(col_text)
                if len(cols) > 1:
                    incident_info = {
                        "No.": cols[1].text,
                        "Time": cols[2].text,
                        "Type": cols[3].text,
                        "Location": cols[4].text,
                        "Location 2": cols[5].text,
                        "Area": cols[6].text,
                        "Details": cols[0].text
                    }
                    print(incident_info["Details"])
                    data.append(incident_info)

            # Print Results
            for item in data:
                print(item)
                
        except Exception:
            print("No incidents found or table failed to load for this center.")

    finally:
        driver.quit()

if __name__ == "__main__":
    scrape_chp_cad()