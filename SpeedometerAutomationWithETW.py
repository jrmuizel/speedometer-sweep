import time
import os
import os.path
import subprocess
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains

# Path to collections of Firefox and GeckoDriver
firefoxen_dir = os.path.normpath("C:/Users/Testing/Desktop/Firefoxen")
geckodriver_dir = os.path.normpath("C:/Users/Testing/Desktop/geckodriver")


def geckodriver_for_rev(rev):
    """Select latest GeckoDriver that still supports target
       version of Firefox.
    """
    return "0.32"

    # Nightyly builds
    if len(rev) == 14:
        if rev <= "20170921100141":
            return "0.17"
        return "0.31"

    major = int(rev.split(".")[0])
    if major >= 102:
        return "0.32"
    if major >= 91:
        return "0.31"
    if major >= 78:
        return "0.30"
    if major >= 60:
        return "0.29.1"
    if major >= 57:
        return "0.25"
    if major >= 52:
        return "0.17"
    if major >= 49:
        return "0.16.1"  # FIXME
    raise Exception("Unsupported firefox version")


def DoGeckoDriverTest(rev, callback):
    """Starts the specified version of Firefox and runs the test
       callback on the WebDriver connection."""

    # We need to use find a geckodriver version that is compatible with
    # the target Firefox revision
    geckodriver_ver = geckodriver_for_rev(rev)

    # Identify the binaries we will test with
    firefoxbin = os.path.join(firefoxen_dir, "firefox-{}".format(rev), "firefox.exe")
    geckodriver = os.path.join(geckodriver_dir, "geckodriver-{}.exe".format(geckodriver_ver))

    # Start a GeckoDriver session
    driver = webdriver.Firefox(executable_path=geckodriver,
                               firefox_binary=firefoxbin)

    # Confirm the browser version is correct and no update shenanigans happened.
    #assert (rev == driver.capabilities["browserVersion"] or
    #        "moz:buildID" not in driver.capabilities or
    #        rev == driver.capabilities["moz:buildID"])

    # Run the test scenario with the driver
    results = callback(driver)

    # Shutdown the browser
    driver.quit()

    return results


def RunSpeedometer(driver):
    """Run Speedometer 2.1 benchmark"""

    # Navigate to Speedometer 2.1
    driver.get("https://browserbench.org/Speedometer2.1/")
    start_button = driver.find_element(
        By.CSS_SELECTOR, "#home .buttons button")

    # Wait a few seconds and then click the button
    actions = ActionChains(driver)
    actions.pause(3)
    actions.click(start_button)
    actions.perform()

    # Wait for the results element to be inserted
    results_element = WebDriverWait(driver, timeout=600, poll_frequency=3).until(
        EC.visibility_of_element_located((By.ID, "result-number")))
    has_outlier = False

    return (results_element.text, has_outlier)


def RunSpeedometer3(driver):
    """Run Speedometer 3 benchmark"""

    # Navigate to Speedometer 3 preview
    driver.get("https://speedometer-preview.netlify.app/")
    start_button = driver.find_element(
        By.CSS_SELECTOR, "#home .buttons button")

    # Wait a few seconds and then click the button
    actions = ActionChains(driver)
    actions.pause(3)
    actions.click(start_button)
    actions.perform()

    # Wait for the results element to be inserted
    WebDriverWait(driver, timeout=600, poll_frequency=3).until(
        EC.visibility_of_element_located((By.ID, "result-number")))
    
    results_json = driver.execute_script("return benchmarkClient.metrics;")
    subtest_names = [key for key in results_json.keys() if not "/" in key and key != "Score" and key != "Geomean" and not key.startswith("Iteration-")]
    async_names = [key for key in results_json.keys() if key.endswith("/Async")]
    has_outlier = False
    for async_name in async_names:
        for i, val in enumerate(results_json[async_name]["values"]):
            if val > 150:
                print("Found an outlier in iteration {} in async step {}".format(i, async_name))
                has_outlier = True

    return (",".join(["{:.2f}".format(results_json["Score"]["mean"])] + ["{:.2f}".format(results_json[subtest_name]["mean"]) for subtest_name in subtest_names]), has_outlier)


def RunMozillaOrg(driver):
    """Load mozilla.org and quit after a few seconds"""
    driver.get("https://mozilla.org/")

    actions = ActionChains(driver)
    actions.pause(1)
    actions.perform()

    return "100"


def KillFirefoxProcesses():
    """Kill all Firefox processes by name"""
    os.system("taskkill /f /im firefox.exe")


def StartXperf():
    subprocess.run(["xperf", "-start", "NT Kernel Logger", "-SetProfInt", "10000", "-on", "latency", "-stackwalk", "profile+cswitch", "-start", "usersession", "-on", "Microsoft-JScript:0x3"])


def StopXperfAndCaptureProfile(filename):
    subprocess.run(["xperf", "-stop", "NT Kernel Logger", "-stop", "usersession", "-d", filename])


def StopXperfAndDiscardProfile():
    subprocess.run(["xperf", "-stop", "NT Kernel Logger", "-stop", "usersession"])


def RunExperimentSeries(builds, test, nrep = 1):
    """Run the specified test over a series of builds"""
    with open("results.csv", "w") as results:
        for run in range(nrep):
            for build in builds:
                try:
                    #core = "111"
                    StartXperf()
                    score, has_outlier = DoGeckoDriverTest(build, test)
                    if has_outlier:
                        print("Found an outlier")
                        StopXperfAndCaptureProfile("prof-with-outlier-{}-{:d}.etl".format(build, run))
                    else:
                        StopXperfAndDiscardProfile()
                except Exception as e:
                    score = "FAIL:" + str(e)
                    StopXperfAndDiscardProfile()
                    KillFirefoxProcesses()

                results.write("{},{}\n".format(build, score))
                results.flush()
                print(build, "->", score)
                time.sleep(3)


def RunReleaseExperiment(firstV, lastV, test, nrep=1):
    builds = ["{}.0".format(v) for v in range(firstV, lastV+1)]
    RunExperimentSeries(builds, test, nrep)


def RunNightlyExperiment(startDate, endDate, test, nrep=1):
    assert len(startDate) == 14
    assert len(endDate) == 14
    assert startDate <= endDate

    builds = []
    for f in os.listdir(firefoxen_dir):
        fx, _, build = f.partition("-")
        assert fx == "firefox"

        if len(build) != 14:
            continue

        if build < startDate or build > endDate:
            continue

        # Skip builds where GeckoDriver acts up
        if "20211004095342" <= build <= "20211015095004":
            print("Skipping:", build)
            continue

        builds.append(build)

    RunExperimentSeries(builds, test, nrep)


time.sleep(2)

#unReleaseExperiment(110, 114, RunSpeedometer3, 1)
#unNightlyExperiment("20170302030206", "20170921100141", RunSpeedometer)
#unNightlyExperiment("20181210220553", "20190128092811", RunSpeedometer)
#unExperimentSeries(["20181210095504", "20181210220553", "20190128092811"], RunSpeedometer)
#unNightlyExperiment("20180600000000", "20250000000000", RunSpeedometer)
#unNightlyExperiment("20200309215254", "20200406092400", RunSpeedometer)
#unNightlyExperiment("20200309091841", "20200309215254", RunSpeedometer)
#unNightlyExperiment("20220700000000", "20250000000000", RunSpeedometer3, 3)

RunNightlyExperiment("20231200000000", "20240100000000", RunSpeedometer3, 50)
