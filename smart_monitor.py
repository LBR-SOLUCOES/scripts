#!/usr/bin/env python3
"""
DATTO RMM S.M.A.R.T. Disk Health Monitor
This script uses SmartMonTools to check S.M.A.R.T. data for HDDs and SSDs
Author: Cascade AI
Date: 2025-03-12
"""

import os
import sys
import subprocess
import re
import json
import tempfile
import zipfile
import urllib.request
import shutil
from datetime import datetime
import ctypes
import platform

# Constants
SMARTMONTOOLS_URL = "https://sourceforge.net/projects/smartmontools/files/smartmontools/7.3/smartmontools-7.3-1.win32-setup.exe/download"
TEMP_DIR = tempfile.gettempdir()
EXTRACT_DIR = os.path.join(TEMP_DIR, "SmartMonTools")
SMARTCTL_PATH = os.path.join(EXTRACT_DIR, "bin", "smartctl.exe")

def is_admin():
    """Check if the script is running with administrative privileges"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def download_file(url, destination):
    """Download a file from a URL to a destination"""
    try:
        print(f"Downloading from {url} to {destination}")
        urllib.request.urlretrieve(url, destination)
        return True
    except Exception as e:
        print(f"Error downloading file: {e}")
        return False

def extract_exe(exe_path, extract_path):
    """Extract files from an executable installer"""
    try:
        # Try to use 7-Zip if available
        seven_zip_path = os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), '7-Zip', '7z.exe')
        if os.path.exists(seven_zip_path):
            subprocess.run([seven_zip_path, 'x', exe_path, f'-o{extract_path}', '-y'], 
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return True
        
        # Otherwise run the installer in silent mode
        subprocess.run([exe_path, '/SILENT', '/SUPPRESSMSGBOXES', f'/DIR="{extract_path}"', '/NOICONS'], 
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception as e:
        print(f"Error extracting files: {e}")
        return False

def initialize_smartmontools():
    """Download and extract SmartMonTools if not already available"""
    if os.path.exists(SMARTCTL_PATH):
        print("SmartMonTools already available.")
        return SMARTCTL_PATH
    
    # Create extraction directory if it doesn't exist
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    
    # Download the installer
    download_path = os.path.join(TEMP_DIR, "smartmontools-setup.exe")
    if not download_file(SMARTMONTOOLS_URL, download_path):
        return None
    
    # Extract the files
    if not extract_exe(download_path, EXTRACT_DIR):
        return None
    
    # Clean up the installer
    try:
        os.remove(download_path)
    except:
        pass
    
    # Verify the smartctl.exe exists
    if not os.path.exists(SMARTCTL_PATH):
        print(f"ERROR: Failed to find smartctl.exe at expected location: {SMARTCTL_PATH}")
        return None
    
    return SMARTCTL_PATH

def run_smartctl(smartctl_path, args):
    """Run smartctl with the given arguments and return the output"""
    try:
        cmd = [smartctl_path] + args
        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                               text=True, encoding='utf-8', errors='replace')
        return process.stdout + process.stderr
    except Exception as e:
        print(f"Error running smartctl: {e}")
        return None

def get_physical_disks(smartctl_path):
    """Get a list of physical disks using smartctl --scan"""
    output = run_smartctl(smartctl_path, ["--scan"])
    if not output:
        return []
    
    disks = []
    for line in output.splitlines():
        if "/dev/" in line:
            disk_id = line.split()[0]
            disks.append(disk_id)
    
    return disks

def parse_temperature(value):
    """Parse temperature value from various formats"""
    if value == "N/A" or not value:
        return "N/A"
    
    # Try to extract numeric part
    match = re.search(r'(\d+)', value)
    if match:
        return f"{match.group(1)} °C"
    
    return f"{value} °C"

def parse_power_on_hours(value):
    """Convert power-on hours to days and hours"""
    if value == "N/A" or not value:
        return "N/A"
    
    try:
        hours = int(value)
        days = hours // 24
        remaining_hours = hours % 24
        return f"{days} days, {remaining_hours} hours"
    except:
        return value

def parse_lba_to_tb(value):
    """Convert LBA sectors to TB (assuming 512 bytes per sector)"""
    if value == "N/A" or not value:
        return "N/A"
    
    try:
        bytes_value = int(value) * 512
        tb_value = round(bytes_value / (1024**4), 2)
        return f"{tb_value} TB"
    except:
        return value

def get_disk_info(smartctl_path, disk_id):
    """Get S.M.A.R.T. information for a disk"""
    disk_info = {
        "Model": "Unknown",
        "SerialNumber": "Unknown",
        "IsSSD": False,
        "HealthStatus": "Unknown",
        "Attributes": {
            "Temperature": "N/A",
            "PowerOnTime": "N/A",
            "ReallocatedSectors": "N/A",
            "PendingSectors": "N/A",
            "UncorrectableSectors": "N/A",
            "LifeRemaining": "N/A",
            "TotalWritten": "N/A",
            "TotalRead": "N/A"
        }
    }
    
    # Get basic disk information
    info_output = run_smartctl(smartctl_path, ["-i", disk_id])
    if not info_output:
        return disk_info
    
    # Parse model
    model_match = re.search(r'Device Model:\s+(.+)', info_output)
    if model_match:
        disk_info["Model"] = model_match.group(1)
    else:
        product_match = re.search(r'Product:\s+(.+)', info_output)
        if product_match:
            disk_info["Model"] = product_match.group(1)
        else:
            model_match = re.search(r'Model Number:\s+(.+)', info_output)
            if model_match:
                disk_info["Model"] = model_match.group(1)
    
    # Parse serial number
    serial_match = re.search(r'Serial Number:\s+(.+)', info_output)
    if serial_match:
        disk_info["SerialNumber"] = serial_match.group(1)
    
    # Determine if it's an SSD
    if "Solid State Device" in info_output or "Rotation Rate: Solid State" in info_output or "NVMe" in info_output:
        disk_info["IsSSD"] = True
    elif "SSD" in disk_info["Model"]:
        disk_info["IsSSD"] = True
    
    # Get health information
    health_output = run_smartctl(smartctl_path, ["-H", disk_id])
    if health_output:
        health_match = re.search(r'SMART overall-health self-assessment test result: (.+)', health_output)
        if health_match:
            disk_info["HealthStatus"] = health_match.group(1)
        else:
            # Try NVMe health status
            nvme_health_match = re.search(r'SMART/Health Information.*\s+(.*(normal|failed).*)', health_output, re.DOTALL)
            if nvme_health_match:
                if "normal" in nvme_health_match.group(1).lower():
                    disk_info["HealthStatus"] = "PASSED"
                else:
                    disk_info["HealthStatus"] = "FAILED"
    
    # Get all SMART attributes
    attr_output = run_smartctl(smartctl_path, ["-A", disk_id])
    if not attr_output:
        return disk_info
    
    # Parse temperature
    temp_match = re.search(r'Temperature_Celsius.*?(\d+)', attr_output)
    if temp_match:
        disk_info["Attributes"]["Temperature"] = f"{temp_match.group(1)} °C"
    else:
        # Try alternative temperature patterns
        alt_temp_match = re.search(r'(Airflow_Temperature_Cel|Temperature).*?(\d+)', attr_output)
        if alt_temp_match:
            disk_info["Attributes"]["Temperature"] = f"{alt_temp_match.group(2)} °C"
        else:
            # Try NVMe temperature
            nvme_temp_match = re.search(r'Temperature:\s+(\d+)\s+Celsius', attr_output)
            if nvme_temp_match:
                disk_info["Attributes"]["Temperature"] = f"{nvme_temp_match.group(1)} °C"
    
    # Parse Power-On Hours
    poh_match = re.search(r'Power_On_Hours.*?(\d+)', attr_output)
    if poh_match:
        disk_info["Attributes"]["PowerOnTime"] = parse_power_on_hours(poh_match.group(1))
    else:
        # Try NVMe power-on hours
        nvme_poh_match = re.search(r'Power On Hours:\s+(\d+)', attr_output)
        if nvme_poh_match:
            disk_info["Attributes"]["PowerOnTime"] = parse_power_on_hours(nvme_poh_match.group(1))
    
    # HDD specific attributes
    if not disk_info["IsSSD"]:
        # Reallocated sectors
        realloc_match = re.search(r'Reallocated_Sector_Ct.*?(\d+)', attr_output)
        if realloc_match:
            disk_info["Attributes"]["ReallocatedSectors"] = realloc_match.group(1)
        
        # Pending sectors
        pending_match = re.search(r'Current_Pending_Sector.*?(\d+)', attr_output)
        if pending_match:
            disk_info["Attributes"]["PendingSectors"] = pending_match.group(1)
        
        # Uncorrectable sectors
        uncorr_match = re.search(r'(Offline_Uncorrectable|Reported_Uncorrect).*?(\d+)', attr_output)
        if uncorr_match:
            disk_info["Attributes"]["UncorrectableSectors"] = uncorr_match.group(2)
    
    # SSD specific attributes
    if disk_info["IsSSD"]:
        # SSD Life/Wear
        wear_match = re.search(r'(Wear_Leveling_Count|Media_Wearout_Indicator).*?(\d+)', attr_output)
        if wear_match:
            if "Media_Wearout_Indicator" in wear_match.group(1):
                try:
                    life_remaining = 100 - int(wear_match.group(2))
                    disk_info["Attributes"]["LifeRemaining"] = f"{life_remaining}%"
                except:
                    disk_info["Attributes"]["LifeRemaining"] = f"{wear_match.group(2)}%"
            else:
                disk_info["Attributes"]["LifeRemaining"] = f"{wear_match.group(2)}%"
        else:
            # Try NVMe percentage used
            nvme_life_match = re.search(r'Percentage Used:\s+(\d+)%', attr_output)
            if nvme_life_match:
                try:
                    life_remaining = 100 - int(nvme_life_match.group(1))
                    disk_info["Attributes"]["LifeRemaining"] = f"{life_remaining}%"
                except:
                    pass
        
        # Total data written
        written_match = re.search(r'Total_LBAs_Written.*?(\d+)', attr_output)
        if written_match:
            disk_info["Attributes"]["TotalWritten"] = parse_lba_to_tb(written_match.group(1))
        else:
            # Try NVMe data written
            nvme_written_match = re.search(r'Data Units Written:\s+([0-9,]+)', attr_output)
            if nvme_written_match:
                written_units = nvme_written_match.group(1).replace(',', '')
                try:
                    # NVMe reports in 512KB units
                    bytes_value = int(written_units) * 512 * 1024
                    tb_value = round(bytes_value / (1024**4), 2)
                    disk_info["Attributes"]["TotalWritten"] = f"{tb_value} TB"
                except:
                    pass
        
        # Total data read
        read_match = re.search(r'Total_LBAs_Read.*?(\d+)', attr_output)
        if read_match:
            disk_info["Attributes"]["TotalRead"] = parse_lba_to_tb(read_match.group(1))
        else:
            # Try NVMe data read
            nvme_read_match = re.search(r'Data Units Read:\s+([0-9,]+)', attr_output)
            if nvme_read_match:
                read_units = nvme_read_match.group(1).replace(',', '')
                try:
                    # NVMe reports in 512KB units
                    bytes_value = int(read_units) * 512 * 1024
                    tb_value = round(bytes_value / (1024**4), 2)
                    disk_info["Attributes"]["TotalRead"] = f"{tb_value} TB"
                except:
                    pass
    
    return disk_info

def main():
    """Main function to run the S.M.A.R.T. monitor"""
    # Check for admin privileges
    if not is_admin():
        print("ERROR: This script requires administrative privileges to run.")
        return 1
    
    try:
        # Initialize SmartMonTools
        print("Initializing SmartMonTools...")
        smartctl_path = initialize_smartmontools()
        
        if not smartctl_path:
            print("ERROR: Failed to initialize SmartMonTools")
            return 1
        
        print(f"Using SmartMonTools at: {smartctl_path}")
        
        # Get list of physical disks
        print("Scanning for physical disks...")
        disk_ids = get_physical_disks(smartctl_path)
        
        if not disk_ids:
            print("ERROR: No physical disks detected.")
            return 1
        
        print("\n===== S.M.A.R.T. Disk Health Report =====")
        print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"System: {platform.node()}")
        print(f"Total Disks: {len(disk_ids)}\n")
        
        # Process each disk
        critical_issues = []
        
        for disk_id in disk_ids:
            try:
                print(f"Processing disk: {disk_id}")
                disk_info = get_disk_info(smartctl_path, disk_id)
                
                disk_type = "SSD" if disk_info["IsSSD"] else "HDD"
                
                print("----------------------------------------")
                print(f"Disk: {disk_id}")
                print(f"Model: {disk_info['Model']}")
                print(f"Type: {disk_type}")
                print(f"Serial: {disk_info['SerialNumber']}")
                print(f"Health Status: {disk_info['HealthStatus']}")
                print(f"Temperature: {disk_info['Attributes']['Temperature']}")
                print(f"Power-On Time: {disk_info['Attributes']['PowerOnTime']}")
                
                # Check for critical issues
                if disk_info["HealthStatus"] != "PASSED" and disk_info["HealthStatus"] != "Unknown":
                    critical_issues.append(f"Disk {disk_id} ({disk_info['Model']}) health status: {disk_info['HealthStatus']}")
                
                # Temperature warning (over 50°C is concerning, over 60°C is critical)
                temp_match = re.search(r'(\d+)', disk_info["Attributes"]["Temperature"])
                if temp_match:
                    temp = int(temp_match.group(1))
                    if temp >= 60:
                        critical_issues.append(f"Disk {disk_id} ({disk_info['Model']}) temperature critical: {disk_info['Attributes']['Temperature']}")
                    elif temp >= 50:
                        critical_issues.append(f"Disk {disk_id} ({disk_info['Model']}) temperature warning: {disk_info['Attributes']['Temperature']}")
                
                if disk_info["IsSSD"]:
                    print(f"SSD Life Remaining: {disk_info['Attributes']['LifeRemaining']}")
                    print(f"Total Data Written: {disk_info['Attributes']['TotalWritten']}")
                    print(f"Total Data Read: {disk_info['Attributes']['TotalRead']}")
                    
                    # Check SSD life remaining
                    life_match = re.search(r'(\d+)%', disk_info["Attributes"]["LifeRemaining"])
                    if life_match:
                        life_remaining = int(life_match.group(1))
                        if life_remaining <= 10:
                            critical_issues.append(f"Disk {disk_id} ({disk_info['Model']}) SSD life critically low: {disk_info['Attributes']['LifeRemaining']}")
                        elif life_remaining <= 20:
                            critical_issues.append(f"Disk {disk_id} ({disk_info['Model']}) SSD life warning: {disk_info['Attributes']['LifeRemaining']}")
                else:
                    print(f"Reallocated Sectors: {disk_info['Attributes']['ReallocatedSectors']}")
                    print(f"Pending Sectors: {disk_info['Attributes']['PendingSectors']}")
                    print(f"Uncorrectable Sectors: {disk_info['Attributes']['UncorrectableSectors']}")
                    
                    # Check for bad sectors
                    if disk_info["Attributes"]["ReallocatedSectors"] != "N/A" and disk_info["Attributes"]["ReallocatedSectors"].isdigit() and int(disk_info["Attributes"]["ReallocatedSectors"]) > 0:
                        critical_issues.append(f"Disk {disk_id} ({disk_info['Model']}) has {disk_info['Attributes']['ReallocatedSectors']} reallocated sectors")
                    
                    if disk_info["Attributes"]["PendingSectors"] != "N/A" and disk_info["Attributes"]["PendingSectors"].isdigit() and int(disk_info["Attributes"]["PendingSectors"]) > 0:
                        critical_issues.append(f"Disk {disk_id} ({disk_info['Model']}) has {disk_info['Attributes']['PendingSectors']} pending sectors")
                    
                    if disk_info["Attributes"]["UncorrectableSectors"] != "N/A" and disk_info["Attributes"]["UncorrectableSectors"].isdigit() and int(disk_info["Attributes"]["UncorrectableSectors"]) > 0:
                        critical_issues.append(f"Disk {disk_id} ({disk_info['Model']}) has {disk_info['Attributes']['UncorrectableSectors']} uncorrectable sectors")
            
            except Exception as e:
                print(f"ERROR processing disk {disk_id}: {e}")
        
        # Summary section
        print("\n===== Summary =====")
        if critical_issues:
            print("CRITICAL ISSUES DETECTED:")
            for issue in critical_issues:
                print(f"- {issue}")
            
            print("\nStatus: WARNING - Critical disk issues detected. See details above.")
            return 1
        else:
            print("All disks appear to be healthy.")
            print("\nStatus: OK - No critical disk issues detected.")
            return 0
    
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")
        import traceback
        print(f"Stack Trace: {traceback.format_exc()}")
        return 1

if __name__ == "__main__":
    # Print start marker for DATTO RMM
    print("<-Start Result->")
    
    try:
        exit_code = main()
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")
        import traceback
        print(f"Stack Trace: {traceback.format_exc()}")
        exit_code = 1
    finally:
        # Print end marker for DATTO RMM
        print("<-End Result->")
        sys.exit(exit_code)
