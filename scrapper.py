import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from data_classes import Incident, IncidentDetails

def scrape_chp_to_json():
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless") # Uncomment to run without a window
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 15)

    try:
        driver.get("https://cad.chp.ca.gov/")
        
        # selecting Los Angeles from the dropdown as a baseline
        center_dropdown = wait.until(EC.presence_of_element_located((By.ID, "ddlComCenter")))
        Select(center_dropdown).select_by_visible_text("Los Angeles")
        
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#gvIncidents tr:nth-child(2)")))
        time.sleep(2) # Settling time for AJAX

        # skip the header row
        rows_elements = driver.find_elements(By.CSS_SELECTOR, "#gvIncidents tr")
        rows_count = len(rows_elements) - 1 

        incidents_list = []

        for i in range(rows_count):
            try:
                # RE-FETCH rows every iteration to prevent StaleElementReferenceException
                current_rows = driver.find_elements(By.CSS_SELECTOR, "#gvIncidents tr")
                row = current_rows[i + 1]
                cols = row.find_elements(By.TAG_NAME, "td")

                incident_obj = Incident(
                    number=cols[1].text.strip(),
                    timestamp=cols[2].text.strip(),
                    type=cols[3].text.strip(),
                    location=cols[4].text.strip(),
                    location_desc=cols[5].text.strip(),
                    area=cols[6].text.strip()
                )

                print(f"Processing Row {i}: Incident {incident_obj.number}")

                details_link = cols[0].find_element(By.TAG_NAME, "a")
                driver.execute_script("arguments[0].click();", details_link)
                
                # Wait for pnlDetailsHeader to match the current incident number
                wait.until(EC.text_to_be_present_in_element(
                    (By.ID, "pnlDetailsHeader"), f"Incident: {incident_obj.number}"
                ))

                panel_element = driver.find_element(By.ID, "pnlDetails")
                panel_text = panel_element.text
                
                lat_lon_val = None
                try:
                    # Lat/Lon
                    lat_lon_element = panel_element.find_element(By.PARTIAL_LINK_TEXT, ".")
                    lat_lon_val = lat_lon_element.text
                except:
                    pass

                incident_obj.details = IncidentDetails(
                    raw_log=[line.strip() for line in panel_text.split('\n') if line.strip()],
                    lat_lon=lat_lon_val,
                    full_text_blob=panel_text
                )

                incidents_list.append(incident_obj.to_dict())

            except Exception as e:
                print(f"Error on row {i} (Incident {i}): {e}")
                continue

        with open("chp_incidents.json", "w", encoding="utf-8") as f:
            json.dump(incidents_list, f, indent=2)
        
        print(f"\nScraping complete. {len(incidents_list)} incidents saved to chp_incidents.json")

    finally:
        driver.quit()

if __name__ == "__main__":
    scrape_chp_to_json()