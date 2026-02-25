import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from data_classes import Incident, IncidentDetails

def scrape_chp_area(area_name: str):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    
    # Try using webdriver_manager but handle if chrome is not found locally easily.
    try:
        service_path = ChromeDriverManager().install()
        driver = webdriver.Chrome(service=Service(service_path), options=options)
    except Exception as e:
        print(f"WebDriver setup failed: {e}")
        return []

    wait = WebDriverWait(driver, 15)

    try:
        driver.get("https://cad.chp.ca.gov/")
        
        center_dropdown = wait.until(EC.presence_of_element_located((By.ID, "ddlComCenter")))
        Select(center_dropdown).select_by_visible_text(area_name)
        
        # Settle
        time.sleep(3)

        rows_elements = driver.find_elements(By.CSS_SELECTOR, "#gvIncidents tr")
        rows_count = len(rows_elements) - 1 
        incidents_list = []

        for i in range(rows_count):
            try:
                current_rows = driver.find_elements(By.CSS_SELECTOR, "#gvIncidents tr")
                if len(current_rows) <= i + 1:
                    break
                row = current_rows[i + 1]
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) < 7:
                    continue

                incident_obj = Incident(
                    number=cols[1].text.strip(),
                    timestamp=cols[2].text.strip(),
                    type=cols[3].text.strip(),
                    location=cols[4].text.strip(),
                    location_desc=cols[5].text.strip(),
                    area=cols[6].text.strip()
                )

                details_link = cols[0].find_element(By.TAG_NAME, "a")
                driver.execute_script("arguments[0].click();", details_link)
                
                try:
                    wait.until(EC.text_to_be_present_in_element(
                        (By.ID, "pnlDetailsHeader"), f"Incident: {incident_obj.number}"
                    ))
                    panel_element = driver.find_element(By.ID, "pnlDetails")
                    panel_text = panel_element.text
                    
                    lat_lon_val = None
                    try:
                        lat_lon_element = panel_element.find_element(By.PARTIAL_LINK_TEXT, ".")
                        lat_lon_val = lat_lon_element.text
                    except: pass

                    incident_obj.details = IncidentDetails(
                        raw_log=[line.strip() for line in panel_text.split('\n') if line.strip()],
                        lat_lon=lat_lon_val,
                        full_text_blob=panel_text
                    )
                except Exception as ex:
                    print(f"Details error for {incident_obj.number}: {ex}")

                incidents_list.append(incident_obj.to_dict())

            except Exception as e:
                print(f"Error on row {i}: {e}")
                continue

        return incidents_list

    finally:
        driver.quit()