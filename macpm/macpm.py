import argparse
import humanize
from collections import deque
from blessed import Terminal
from dashing import VSplit, HSplit, HGauge, HChart, VGauge, HBrailleChart, HBrailleFilledChart
import os, time
import subprocess
from subprocess import PIPE
import psutil
import plistlib

version = 'macpm v0.14'
parser = argparse.ArgumentParser(
    description=f'{version}: Performance monitoring CLI tool for Apple Silicon')
parser.add_argument('--interval', type=int, default=1,
                    help='Display interval and sampling interval for powermetrics (seconds)')
parser.add_argument('--color', type=int, default=2,
                    help='Choose display color (0~8)')
parser.add_argument('--avg', type=int, default=30,
                    help='Interval for averaged values (seconds)')
parser.add_argument('--show_cores', type=bool, default=False,
                    help='Choose show cores mode')

args = parser.parse_args()

powermetrics_process = None

def clear_console():
    command = 'clear'
    os.system(command)


def convert_to_GB(value):
    return round(value/1024/1024/1024, 1)


def get_ram_metrics_dict():
    ram_metrics = psutil.virtual_memory()
    swap_metrics = psutil.swap_memory()
    total_GB = convert_to_GB(ram_metrics.total)
    free_GB = convert_to_GB(ram_metrics.available)
    used_GB = convert_to_GB(ram_metrics.total-ram_metrics.available)
    swap_total_GB = convert_to_GB(swap_metrics.total)
    swap_used_GB = convert_to_GB(swap_metrics.used)
    swap_free_GB = convert_to_GB(swap_metrics.total-swap_metrics.used)
    if swap_total_GB > 0:
        swap_free_percent = int(100-(swap_free_GB/swap_total_GB*100))
    else:
        swap_free_percent = None
    ram_metrics_dict = {
        "total_GB": round(total_GB, 1),
        "free_GB": round(free_GB, 1),
        "used_GB": round(used_GB, 1),
        "free_percent": int(100-(ram_metrics.available/ram_metrics.total*100)),
        "swap_total_GB": swap_total_GB,
        "swap_used_GB": swap_used_GB,
        "swap_free_GB": swap_free_GB,
        "swap_free_percent": swap_free_percent,
    }
    return ram_metrics_dict


def get_cpu_info():
    cpu_info = os.popen('sysctl -a | grep machdep.cpu').read()
    cpu_info_lines = cpu_info.split("\n")
    data_fields = ["machdep.cpu.brand_string", "machdep.cpu.core_count"]
    cpu_info_dict = {}
    for l in cpu_info_lines:
        for h in data_fields:
            if h in l:
                value = l.split(":")[1].strip()
                cpu_info_dict[h] = value
    return cpu_info_dict


def get_core_counts():
    cores_info = os.popen('sysctl -a | grep hw.perflevel').read()
    cores_info_lines = cores_info.split("\n")
    data_fields = ["hw.perflevel0.logicalcpu", "hw.perflevel1.logicalcpu"]
    cores_info_dict = {}
    for l in cores_info_lines:
        for h in data_fields:
            if h in l:
                value = int(l.split(":")[1].strip())
                cores_info_dict[h] = value
    return cores_info_dict


def get_gpu_cores():
    try:
        cores = os.popen(
            "system_profiler -detailLevel basic SPDisplaysDataType | grep 'Total Number of Cores'").read()
        cores = int(cores.split(": ")[-1])
    except:
        cores = "?"
    return cores


def get_soc_info():
    cpu_info_dict = get_cpu_info()
    core_counts_dict = get_core_counts()
    try:
        e_core_count = core_counts_dict["hw.perflevel1.logicalcpu"]
        p_core_count = core_counts_dict["hw.perflevel0.logicalcpu"]
    except:
        e_core_count = "?"
        p_core_count = "?"
    soc_info = {
        "name": cpu_info_dict["machdep.cpu.brand_string"],
        "core_count": int(cpu_info_dict["machdep.cpu.core_count"]),
        "cpu_max_power": None,
        "gpu_max_power": None,
        "cpu_max_bw": None,
        "gpu_max_bw": None,
        "e_core_count": e_core_count,
        "p_core_count": p_core_count,
        "gpu_core_count": get_gpu_cores()
    }
    # TDP (power)
    if soc_info["name"] == "Apple M1 Max":
        soc_info["cpu_max_power"] = 30
        soc_info["gpu_max_power"] = 60
    elif soc_info["name"] == "Apple M1 Pro":
        soc_info["cpu_max_power"] = 30
        soc_info["gpu_max_power"] = 30
    elif soc_info["name"] == "Apple M1":
        soc_info["cpu_max_power"] = 20
        soc_info["gpu_max_power"] = 20
    elif soc_info["name"] == "Apple M1 Ultra":
        soc_info["cpu_max_power"] = 60
        soc_info["gpu_max_power"] = 120
    elif soc_info["name"] == "Apple M2":
        soc_info["cpu_max_power"] = 25
        soc_info["gpu_max_power"] = 15
    else:
        soc_info["cpu_max_power"] = 20
        soc_info["gpu_max_power"] = 20
    # bandwidth
    if soc_info["name"] == "Apple M1 Max":
        soc_info["cpu_max_bw"] = 250
        soc_info["gpu_max_bw"] = 400
    elif soc_info["name"] == "Apple M1 Pro":
        soc_info["cpu_max_bw"] = 200
        soc_info["gpu_max_bw"] = 200
    elif soc_info["name"] == "Apple M1":
        soc_info["cpu_max_bw"] = 70
        soc_info["gpu_max_bw"] = 70
    elif soc_info["name"] == "Apple M1 Ultra":
        soc_info["cpu_max_bw"] = 500
        soc_info["gpu_max_bw"] = 800
    elif soc_info["name"] == "Apple M2":
        soc_info["cpu_max_bw"] = 100
        soc_info["gpu_max_bw"] = 100
    else:
        soc_info["cpu_max_bw"] = 70
        soc_info["gpu_max_bw"] = 70
    return soc_info

def parse_thermal_pressure(powermetrics_parse):
    return powermetrics_parse["thermal_pressure"]


def parse_bandwidth_metrics(powermetrics_parse):
    bandwidth_metrics = powermetrics_parse["bandwidth_counters"]
    bandwidth_metrics_dict = {}
    data_fields = ["PCPU0 DCS RD", "PCPU0 DCS WR",
                   "PCPU1 DCS RD", "PCPU1 DCS WR",
                   "PCPU2 DCS RD", "PCPU2 DCS WR",
                   "PCPU3 DCS RD", "PCPU3 DCS WR",
                   "PCPU DCS RD", "PCPU DCS WR",
                   "ECPU0 DCS RD", "ECPU0 DCS WR",
                   "ECPU1 DCS RD", "ECPU1 DCS WR",
                   "ECPU DCS RD", "ECPU DCS WR",
                   "GFX DCS RD", "GFX DCS WR",
                   "ISP DCS RD", "ISP DCS WR",
                   "STRM CODEC DCS RD", "STRM CODEC DCS WR",
                   "PRORES DCS RD", "PRORES DCS WR",
                   "VDEC DCS RD", "VDEC DCS WR",
                   "VENC0 DCS RD", "VENC0 DCS WR",
                   "VENC1 DCS RD", "VENC1 DCS WR",
                   "VENC2 DCS RD", "VENC2 DCS WR",
                   "VENC3 DCS RD", "VENC3 DCS WR",
                   "VENC DCS RD", "VENC DCS WR",
                   "JPG0 DCS RD", "JPG0 DCS WR",
                   "JPG1 DCS RD", "JPG1 DCS WR",
                   "JPG2 DCS RD", "JPG2 DCS WR",
                   "JPG3 DCS RD", "JPG3 DCS WR",
                   "JPG DCS RD", "JPG DCS WR",
                   "DCS RD", "DCS WR"]
    for h in data_fields:
        bandwidth_metrics_dict[h] = 0
    for l in bandwidth_metrics:
        if l["name"] in data_fields:
            bandwidth_metrics_dict[l["name"]] = l["value"]/(1e9)
    bandwidth_metrics_dict["PCPU DCS RD"] = bandwidth_metrics_dict["PCPU DCS RD"] + \
        bandwidth_metrics_dict["PCPU0 DCS RD"] + \
        bandwidth_metrics_dict["PCPU1 DCS RD"] + \
        bandwidth_metrics_dict["PCPU2 DCS RD"] + \
        bandwidth_metrics_dict["PCPU3 DCS RD"]
    bandwidth_metrics_dict["PCPU DCS WR"] = bandwidth_metrics_dict["PCPU DCS WR"] + \
        bandwidth_metrics_dict["PCPU0 DCS WR"] + \
        bandwidth_metrics_dict["PCPU1 DCS WR"] + \
        bandwidth_metrics_dict["PCPU2 DCS WR"] + \
        bandwidth_metrics_dict["PCPU3 DCS WR"]
    bandwidth_metrics_dict["JPG DCS RD"] = bandwidth_metrics_dict["JPG DCS RD"] + \
        bandwidth_metrics_dict["JPG0 DCS RD"] + \
        bandwidth_metrics_dict["JPG1 DCS RD"] + \
        bandwidth_metrics_dict["JPG2 DCS RD"] + \
        bandwidth_metrics_dict["JPG3 DCS RD"]
    bandwidth_metrics_dict["JPG DCS WR"] = bandwidth_metrics_dict["JPG DCS WR"] + \
        bandwidth_metrics_dict["JPG0 DCS WR"] + \
        bandwidth_metrics_dict["JPG1 DCS WR"] + \
        bandwidth_metrics_dict["JPG2 DCS WR"] + \
        bandwidth_metrics_dict["JPG3 DCS WR"]
    bandwidth_metrics_dict["VENC DCS RD"] = bandwidth_metrics_dict["VENC DCS RD"] + \
        bandwidth_metrics_dict["VENC0 DCS RD"] + \
        bandwidth_metrics_dict["VENC1 DCS RD"] + \
        bandwidth_metrics_dict["VENC2 DCS RD"] + \
        bandwidth_metrics_dict["VENC3 DCS RD"]
    bandwidth_metrics_dict["VENC DCS WR"] = bandwidth_metrics_dict["VENC DCS WR"] + \
        bandwidth_metrics_dict["VENC0 DCS WR"] + \
        bandwidth_metrics_dict["VENC1 DCS WR"] + \
        bandwidth_metrics_dict["VENC2 DCS WR"] + \
        bandwidth_metrics_dict["VENC3 DCS WR"]
    bandwidth_metrics_dict["MEDIA DCS"] = sum([
        bandwidth_metrics_dict["ISP DCS RD"], bandwidth_metrics_dict["ISP DCS WR"],
        bandwidth_metrics_dict["STRM CODEC DCS RD"], bandwidth_metrics_dict["STRM CODEC DCS WR"],
        bandwidth_metrics_dict["PRORES DCS RD"], bandwidth_metrics_dict["PRORES DCS WR"],
        bandwidth_metrics_dict["VDEC DCS RD"], bandwidth_metrics_dict["VDEC DCS WR"],
        bandwidth_metrics_dict["VENC DCS RD"], bandwidth_metrics_dict["VENC DCS WR"],
        bandwidth_metrics_dict["JPG DCS RD"], bandwidth_metrics_dict["JPG DCS WR"],
    ])
    return bandwidth_metrics_dict


def parse_cpu_metrics(powermetrics_parse):
    e_core = []
    p_core = []
    cpu_metrics = powermetrics_parse["processor"]
    cpu_metric_dict = {}
    # cpu_clusters
    cpu_clusters = cpu_metrics["clusters"]
    e_total_idle_ratio = 0
    e_core_count = 0
    p_total_idle_ratio = 0
    p_core_count = 0
    for cluster in cpu_clusters:
        name = cluster["name"]
        cpu_metric_dict[name+"_freq_Mhz"] = int(cluster["freq_hz"]/(1e6))
        cpu_metric_dict[name+"_active"] = int((1 - cluster["idle_ratio"])*100)
        for cpu in cluster["cpus"]:
            name = 'E-Cluster' if name[0] == 'E' else 'P-Cluster'
            core = e_core if name[0] == 'E' else p_core
            core.append(cpu["cpu"])
            cpu_metric_dict[name + str(cpu["cpu"]) + "_freq_Mhz"] = int(cpu["freq_hz"] / (1e6))
            cpu_metric_dict[name + str(cpu["cpu"]) + "_active"] = int((1 - cpu["idle_ratio"]) * 100)
            if name[0] == 'E':
                e_total_idle_ratio += cluster["down_ratio"] + (1 - cluster["down_ratio"]) * (cpu["idle_ratio"] + cpu["down_ratio"])
                e_core_count += 1
            else:
                p_total_idle_ratio += cluster["down_ratio"] + (1 - cluster["down_ratio"]) * (cpu["idle_ratio"] + cpu["down_ratio"])
                p_core_count += 1
    
    cpu_metric_dict["E-Cluster_active"] = int((1 - e_total_idle_ratio/e_core_count)*100)
    cpu_metric_dict["P-Cluster_active"] = int((1 - p_total_idle_ratio/p_core_count)*100)
    cpu_metric_dict["e_core"] = e_core
    cpu_metric_dict["p_core"] = p_core
    if "E-Cluster_active" not in cpu_metric_dict:
        # M1 Ultra
        cpu_metric_dict["E-Cluster_active"] = int(
            (cpu_metric_dict["E0-Cluster_active"] + cpu_metric_dict["E1-Cluster_active"])/2)
    if "E-Cluster_freq_Mhz" not in cpu_metric_dict:
        # M1 Ultra
        cpu_metric_dict["E-Cluster_freq_Mhz"] = max(
            cpu_metric_dict["E0-Cluster_freq_Mhz"], cpu_metric_dict["E1-Cluster_freq_Mhz"])
    if "P-Cluster_active" not in cpu_metric_dict:
        if "P2-Cluster_active" in cpu_metric_dict:
            # M1 Ultra
            cpu_metric_dict["P-Cluster_active"] = int((cpu_metric_dict["P0-Cluster_active"] + cpu_metric_dict["P1-Cluster_active"] +
                                                      cpu_metric_dict["P2-Cluster_active"] + cpu_metric_dict["P3-Cluster_active"]) / 4)
        else:
            cpu_metric_dict["P-Cluster_active"] = int(
                (cpu_metric_dict["P0-Cluster_active"] + cpu_metric_dict["P1-Cluster_active"])/2)
    if "P-Cluster_freq_Mhz" not in cpu_metric_dict:
        if "P2-Cluster_freq_Mhz" in cpu_metric_dict:
            # M1 Ultra
            freqs = [
                cpu_metric_dict["P0-Cluster_freq_Mhz"],
                cpu_metric_dict["P1-Cluster_freq_Mhz"],
                cpu_metric_dict["P2-Cluster_freq_Mhz"],
                cpu_metric_dict["P3-Cluster_freq_Mhz"]]
            cpu_metric_dict["P-Cluster_freq_Mhz"] = max(freqs)
        else:
            cpu_metric_dict["P-Cluster_freq_Mhz"] = max(
                cpu_metric_dict["P0-Cluster_freq_Mhz"], cpu_metric_dict["P1-Cluster_freq_Mhz"])
    # power
    cpu_metric_dict["ane_W"] = cpu_metrics["ane_energy"]/1000
    #cpu_metric_dict["dram_W"] = cpu_metrics["dram_energy"]/1000
    cpu_metric_dict["cpu_W"] = cpu_metrics["cpu_energy"]/1000
    cpu_metric_dict["gpu_W"] = cpu_metrics["gpu_energy"]/1000
    cpu_metric_dict["package_W"] = cpu_metrics["combined_power"]/1000
    return cpu_metric_dict


def parse_gpu_metrics(powermetrics_parse):
    gpu_metrics = powermetrics_parse["gpu"]
    gpu_metrics_dict = {
        "freq_MHz": int(gpu_metrics["freq_hz"]),
        "active": int((1 - gpu_metrics["idle_ratio"])*100),
    }
    return gpu_metrics_dict

def parse_disk_metrics(powermetrics_parse):
    disk_metrics = powermetrics_parse["disk"]
    disk_metrics_dict = {
        "read_iops": int(disk_metrics["rops_per_s"]),
        "write_iops": int(disk_metrics["wops_per_s"]),
        "read_Bps": int(disk_metrics["rbytes_per_s"]),
        "write_Bps": int(disk_metrics["wbytes_per_s"]),
    }
    return disk_metrics_dict

def parse_network_metrics(powermetrics_parse):
    network_metrics = powermetrics_parse["network"]
    network_metrics_dict = {
        "out_Bps": int(network_metrics["obyte_rate"]),
        "in_Bps": int(network_metrics["ibyte_rate"]),
    }
    return network_metrics_dict


def main():
    print("\nmacpm - Performance monitoring CLI tool for Apple Silicon")
    print("You can update macpm by running `pip install macpm --upgrade`")
    print("Get help at `https://github.com/visualcjy/macpm`")
    print("P.S. You are recommended to run macpm with `sudo macpm`\n")
    print("\n[1/3] Loading macpm\n")
    print("\033[?25l")
    global powermetrics_process
    cpu1_gauge = HGauge(title="E-CPU Usage", val=0, color=args.color)
    cpu2_gauge = HGauge(title="P-CPU Usage", val=0, color=args.color)
    gpu_gauge = HGauge(title="GPU Usage", val=0, color=args.color)
    ane_gauge = HGauge(title="ANE", val=0, color=args.color)
    gpu_ane_gauges = [gpu_gauge, ane_gauge]

    soc_info_dict = get_soc_info()
    e_core_count = soc_info_dict["e_core_count"]
    e_core_gauges = [VGauge(val=0, color=args.color, border_color=args.color) for _ in range(e_core_count)]
    p_core_count = soc_info_dict["p_core_count"]
    p_core_gauges = [VGauge(val=0, color=args.color, border_color=args.color) for _ in range(min(p_core_count, 8))]
    p_core_split = [HSplit(
        *p_core_gauges,
    )]
    if p_core_count > 8:
        p_core_gauges_ext = [VGauge(val=0, color=args.color, border_color=args.color) for _ in range(p_core_count - 8)]
        p_core_split.append(HSplit(
            *p_core_gauges_ext,
        ))
    processor_gauges = [cpu1_gauge,
                        HSplit(*e_core_gauges),
                        cpu2_gauge,
                        *p_core_split,
                        *gpu_ane_gauges
                        ] if args.show_cores else [
        HSplit(cpu1_gauge, cpu2_gauge),
        HSplit(*gpu_ane_gauges)
    ]
    processor_split = VSplit(
        *processor_gauges,
        title="Processor Utilization",
        border_color=args.color,
    )

    ram_gauge = HGauge(title="RAM Usage", val=0, color=args.color)
    """
    ecpu_bw_gauge = HGauge(title="E-CPU B/W", val=50, color=args.color)
    pcpu_bw_gauge = HGauge(title="P-CPU B/W", val=50, color=args.color)
    gpu_bw_gauge = HGauge(title="GPU B/W", val=50, color=args.color)
    media_bw_gauge = HGauge(title="Media B/W", val=50, color=args.color)
    bw_gauges = [HSplit(
        ecpu_bw_gauge,
        pcpu_bw_gauge,
    ),
        HSplit(
            gpu_bw_gauge,
            media_bw_gauge,
        )] if args.show_cores else [
        HSplit(
            ecpu_bw_gauge,
            pcpu_bw_gauge,
            gpu_bw_gauge,
            media_bw_gauge,
        )]
    """
    memory_gauges = VSplit(
        ram_gauge,
        #*bw_gauges,
        border_color=args.color,
        title="Memory"
    )

    cpu_power_chart = HChart(title="CPU Power", color=args.color)
    gpu_power_chart = HChart(title="GPU Power", color=args.color)
    power_charts = VSplit(
        cpu_power_chart,
        gpu_power_chart,
        title="Power Chart",
        border_color=args.color,
    ) if args.show_cores else HSplit(
        cpu_power_chart,
        gpu_power_chart,
        title="Power Chart",
        border_color=args.color,
    )

    disk_read_iops_charts = HChart(title="read iops", color=args.color)
    disk_write_iops_charts = HChart(title="write iops", color=args.color)
    disk_read_bps_charts = HChart(title="read Bps", color=args.color)
    disk_write_bps_charts = HChart(title="write Bps", color=args.color)
    network_in_bps_charts = HChart(title="in Bps", color=args.color)
    network_out_bps_charts = HChart(title="out Bps", color=args.color)
    disk_io_charts = HSplit(
        VSplit(disk_read_iops_charts,
        disk_write_iops_charts,),
        VSplit(disk_read_bps_charts,
        disk_write_bps_charts,),
        title="Disk IO", 
        color=args.color,
        border_color=args.color)
    
    network_io_charts = HSplit(
        network_in_bps_charts,
        network_out_bps_charts,
        title="Network IO", 
        color=args.color,
        border_color=args.color)
    
    ui = HSplit(
        processor_split,
        VSplit(
            memory_gauges,
            power_charts,
            disk_io_charts,
            network_io_charts,
        )
    ) if args.show_cores else VSplit(
        processor_split,
        memory_gauges,
        power_charts,
        disk_io_charts,
        network_io_charts,
    )
    """
    ui.title = "".join([
        version,
        "  (Press q or ESC to stop)"
    ])
    ui.border_color = args.color
    """
    usage_gauges = ui.items[0]
    #bw_gauges = memory_gauges.items[1]

    cpu_title = "".join([
        soc_info_dict["name"],
        " (cores: ",
        str(soc_info_dict["e_core_count"]),
        "E+",
        str(soc_info_dict["p_core_count"]),
        "P+",
        str(soc_info_dict["gpu_core_count"]),
        "GPU)"
    ])
    usage_gauges.title = cpu_title
    cpu_max_power = soc_info_dict["cpu_max_power"]
    gpu_max_power = soc_info_dict["gpu_max_power"]
    ane_max_power = 16.0
    """max_cpu_bw = soc_info_dict["cpu_max_bw"]
    max_gpu_bw = soc_info_dict["gpu_max_bw"]
    max_media_bw = 7.0"""

    cpu_peak_power = 0
    gpu_peak_power = 0
    package_peak_power = 0
    disk_read_iops_peak = 0
    disk_write_iops_peak = 0
    disk_read_bps_peak = 0
    disk_write_bps_peak = 0
    network_in_bps_peak = 0
    network_out_bps_peak = 0

    print("\n[2/3] Starting powermetrics process\n")

    command = " ".join([
        "sudo nice -n",
        str(10),
        "powermetrics",
        "--samplers cpu_power,gpu_power,thermal,network,disk",
        "-f plist",
        "-i",
        str(args.interval * 1000)
    ])
    process = subprocess.Popen(command.split(" "), stdin=PIPE, stdout=PIPE)
 
    powermetrics_process = process

    print("\n[3/3] Waiting for first reading...\n")
    """
    def get_reading(wait=0.1):
        ready = parse_powermetrics(timecode=timecode)
        while not ready:
            time.sleep(wait)
            ready = parse_powermetrics(timecode=timecode)
        return ready

    ready = get_reading()
    last_timestamp = ready[-1]
    """
    def get_avg(inlist):
        avg = sum(inlist) / len(inlist)
        return avg

    avg_package_power_list = deque([], maxlen=int(args.avg / args.interval))
    avg_cpu_power_list = deque([], maxlen=int(args.avg / args.interval))
    avg_gpu_power_list = deque([], maxlen=int(args.avg / args.interval))

    clear_console()
    term = Terminal()
    try:
        data = b''
        while True:
            output = process.stdout.readline()
            #output, stderr = process.communicate()
            if process.poll() is not None:
                break
            data = data + output
            str_output = output.decode()
            if str_output.startswith('</plist>'):
                data = data.replace(b'\x00',b'')
                powermetrics_parse = plistlib.loads(data)
                thermal_pressure = parse_thermal_pressure(powermetrics_parse)
                cpu_metrics_dict = parse_cpu_metrics(powermetrics_parse)
                gpu_metrics_dict = parse_gpu_metrics(powermetrics_parse)
                disk_metrics_dict = parse_disk_metrics(powermetrics_parse)
                network_metrics_dict = parse_network_metrics(powermetrics_parse)
                #bandwidth_metrics = parse_bandwidth_metrics(powermetrics_parse)
                bandwidth_metrics = None
                timestamp = powermetrics_parse["timestamp"]
                data = b''
                if timestamp :
                    if thermal_pressure == "Nominal":
                        thermal_throttle = "no"
                    else:
                        thermal_throttle = "yes"

                    """e_cpu_usage = 0
                    core_count = 0
                    for i in cpu_metrics_dict["e_core"]:
                        e_cpu_usage += cpu_metrics_dict["E-Cluster" + str(i) + "_active"]
                        core_count += 1
                    e_cpu_usage = (e_cpu_usage / core_count) if core_count > 0 else  0"""
                    cpu1_gauge.title = "".join([
                        "E-CPU Usage: ",
                        str(cpu_metrics_dict["E-Cluster_active"]),
                        "% @ ",
                        str(cpu_metrics_dict["E-Cluster_freq_Mhz"]),
                        " MHz"
                    ])
                    cpu1_gauge.value = cpu_metrics_dict["E-Cluster_active"]

                    """p_cpu_usage = 0
                    core_count = 0
                    for i in cpu_metrics_dict["p_core"]:
                        p_cpu_usage += cpu_metrics_dict["P-Cluster" + str(i) + "_active"]
                        core_count += 1
                    p_cpu_usage = (p_cpu_usage / core_count) if core_count > 0 else  0"""
                    cpu2_gauge.title = "".join([
                        "P-CPU Usage: ",
                        str(cpu_metrics_dict["P-Cluster_active"]),
                        "% @ ",
                        str(cpu_metrics_dict["P-Cluster_freq_Mhz"]),
                        " MHz"
                    ])
                    cpu2_gauge.value = cpu_metrics_dict["P-Cluster_active"]

                    if args.show_cores:
                        core_count = 0
                        for i in cpu_metrics_dict["e_core"]:
                            e_core_gauges[core_count % 4].title = "".join([
                                "Core-" + str(i + 1) + " ",
                                str(cpu_metrics_dict["E-Cluster" + str(i) + "_active"]),
                                "%",
                            ])
                            e_core_gauges[core_count % 4].value = cpu_metrics_dict["E-Cluster" + str(i) + "_active"]
                            core_count += 1
                        core_count = 0
                        for i in cpu_metrics_dict["p_core"]:
                            core_gauges = p_core_gauges if core_count < 8 else p_core_gauges_ext
                            core_gauges[core_count % 8].title = "".join([
                                ("Core-" if p_core_count < 6 else 'C-') + str(i + 1) + " ",
                                str(cpu_metrics_dict["P-Cluster" + str(i) + "_active"]),
                                "%",
                            ])
                            core_gauges[core_count % 8].value = cpu_metrics_dict["P-Cluster" + str(i) + "_active"]
                            core_count += 1

                    gpu_gauge.title = "".join([
                        "GPU Usage: ",
                        str(gpu_metrics_dict["active"]),
                        "% @ ",
                        str(gpu_metrics_dict["freq_MHz"]),
                        " MHz"
                    ])
                    gpu_gauge.value = gpu_metrics_dict["active"]

                    ane_power_W = cpu_metrics_dict["ane_W"] / args.interval
                    if ane_power_W > ane_max_power:
                        ane_max_power = ane_power_W
                    ane_util_percent = int(
                        ane_power_W / ane_max_power * 100)
                    ane_gauge.title = "".join([
                        "ANE Usage: ",
                        str(ane_util_percent),
                        "% @ ",
                        '{0:.1f}'.format(ane_power_W),
                        " W"
                    ])
                    ane_gauge.value = ane_util_percent

                    ram_metrics_dict = get_ram_metrics_dict()

                    if ram_metrics_dict["swap_total_GB"] < 0.1:
                        ram_gauge.title = "".join([
                            "RAM Usage: ",
                            str(ram_metrics_dict["used_GB"]),
                            "/",
                            str(ram_metrics_dict["total_GB"]),
                            "GB - swap inactive"
                        ])
                    else:
                        ram_gauge.title = "".join([
                            "RAM Usage: ",
                            str(ram_metrics_dict["used_GB"]),
                            "/",
                            str(ram_metrics_dict["total_GB"]),
                            "GB",
                            " - swap:",
                            str(ram_metrics_dict["swap_used_GB"]),
                            "/",
                            str(ram_metrics_dict["swap_total_GB"]),
                            "GB"
                        ])
                    ram_gauge.value = ram_metrics_dict["free_percent"]

                    """

                    ecpu_bw_percent = int(
                        (bandwidth_metrics["ECPU DCS RD"] + bandwidth_metrics[
                            "ECPU DCS WR"]) / args.interval / max_cpu_bw * 100)
                    ecpu_read_GB = bandwidth_metrics["ECPU DCS RD"] / \
                                   args.interval
                    ecpu_write_GB = bandwidth_metrics["ECPU DCS WR"] / \
                                    args.interval
                    ecpu_bw_gauge.title = "".join([
                        "E-CPU: ",
                        '{0:.1f}'.format(ecpu_read_GB + ecpu_write_GB),
                        "GB/s"
                    ])
                    ecpu_bw_gauge.value = ecpu_bw_percent

                    pcpu_bw_percent = int(
                        (bandwidth_metrics["PCPU DCS RD"] + bandwidth_metrics[
                            "PCPU DCS WR"]) / args.interval / max_cpu_bw * 100)
                    pcpu_read_GB = bandwidth_metrics["PCPU DCS RD"] / \
                                   args.interval
                    pcpu_write_GB = bandwidth_metrics["PCPU DCS WR"] / \
                                    args.interval
                    pcpu_bw_gauge.title = "".join([
                        "P-CPU: ",
                        '{0:.1f}'.format(pcpu_read_GB + pcpu_write_GB),
                        "GB/s"
                    ])
                    pcpu_bw_gauge.value = pcpu_bw_percent

                    gpu_bw_percent = int(
                        (bandwidth_metrics["GFX DCS RD"] + bandwidth_metrics["GFX DCS WR"]) / max_gpu_bw * 100)
                    gpu_read_GB = bandwidth_metrics["GFX DCS RD"]
                    gpu_write_GB = bandwidth_metrics["GFX DCS WR"]
                    gpu_bw_gauge.title = "".join([
                        "GPU: ",
                        '{0:.1f}'.format(gpu_read_GB + gpu_write_GB),
                        "GB/s"
                    ])
                    gpu_bw_gauge.value = gpu_bw_percent

                    media_bw_percent = int(
                        bandwidth_metrics["MEDIA DCS"] / args.interval / max_media_bw * 100)
                    media_bw_gauge.title = "".join([
                        "Media: ",
                        '{0:.1f}'.format(
                            bandwidth_metrics["MEDIA DCS"] / args.interval),
                        "GB/s"
                    ])
                    media_bw_gauge.value = media_bw_percent

                    total_bw_GB = (
                                          bandwidth_metrics["DCS RD"] + bandwidth_metrics["DCS WR"]) / args.interval
                    bw_gauges.title = "".join([
                        "Memory Bandwidth: ",
                        '{0:.2f}'.format(total_bw_GB),
                        " GB/s (R:",
                        '{0:.2f}'.format(
                            bandwidth_metrics["DCS RD"] / args.interval),
                        "/W:",
                        '{0:.2f}'.format(
                            bandwidth_metrics["DCS WR"] / args.interval),
                        " GB/s)"
                    ])
                    if args.show_cores:
                        bw_gauges_ext = memory_gauges.items[2]
                        bw_gauges_ext.title = "Memory Bandwidth:"
                    """

                    package_power_W = cpu_metrics_dict["package_W"] / \
                                      args.interval
                    if package_power_W > package_peak_power:
                        package_peak_power = package_power_W
                    avg_package_power_list.append(package_power_W)
                    avg_package_power = get_avg(avg_package_power_list)
                    power_charts.title = "".join([
                        "CPU+GPU+ANE Power: ",
                        '{0:.2f}'.format(package_power_W),
                        "W (avg: ",
                        '{0:.2f}'.format(avg_package_power),
                        "W peak: ",
                        '{0:.2f}'.format(package_peak_power),
                        "W) throttle: ",
                        thermal_throttle,
                    ])

                    cpu_power_W = cpu_metrics_dict["cpu_W"] / args.interval
                    if cpu_power_W > cpu_peak_power:
                        cpu_peak_power = cpu_power_W
                    if cpu_power_W > cpu_max_power:
                        cpu_max_power = cpu_power_W
                    cpu_power_percent = int(
                        cpu_power_W / cpu_max_power * 100)                   
                    avg_cpu_power_list.append(cpu_power_W)
                    avg_cpu_power = get_avg(avg_cpu_power_list)
                    cpu_power_chart.title = "".join([
                        "CPU: ",
                        '{0:.2f}'.format(cpu_power_W),
                        "W (avg: ",
                        '{0:.2f}'.format(avg_cpu_power),
                        "W peak: ",
                        '{0:.2f}'.format(cpu_peak_power),
                        "W)"
                    ])
                    cpu_power_chart.append(cpu_power_percent)

                    gpu_power_W = cpu_metrics_dict["gpu_W"] / args.interval
                    if gpu_power_W > gpu_peak_power:
                        gpu_peak_power = gpu_power_W
                    if gpu_power_W > gpu_max_power:
                        gpu_max_power = gpu_power_W
                    gpu_power_percent = int(
                        gpu_power_W / gpu_max_power * 100)
                    avg_gpu_power_list.append(gpu_power_W)
                    avg_gpu_power = get_avg(avg_gpu_power_list)
                    gpu_power_chart.title = "".join([
                        "GPU: ",
                        '{0:.2f}'.format(gpu_power_W),
                        "W (avg: ",
                        '{0:.2f}'.format(avg_gpu_power),
                        "W peak: ",
                        '{0:.2f}'.format(gpu_peak_power),
                        "W)"
                    ])
                    gpu_power_chart.append(gpu_power_percent)

                    def format_number(number):
                        return humanize.naturalsize(number)

                    disk_read_iops = disk_metrics_dict["read_iops"]
                    if disk_read_iops > disk_read_iops_peak:
                        disk_read_iops_peak = disk_read_iops
                    disk_read_iops_charts.title = "Read iops: "+ f'{disk_read_iops} (peak: {disk_read_iops_peak})'
                    if disk_read_iops_charts.datapoints:
                        disk_read_iops_rate = int(disk_read_iops / disk_read_iops_peak * 100) if disk_read_iops_peak > 0 else 0
                    else:
                        disk_read_iops_rate = 100
                    disk_read_iops_charts.append(disk_read_iops_rate)

                    disk_write_iops = disk_metrics_dict["write_iops"]
                    if disk_write_iops > disk_write_iops_peak:
                        disk_write_iops_peak = disk_write_iops
                    disk_write_iops_charts.title = "Write iops: "+ f'{disk_write_iops} (peak: {disk_write_iops_peak})'
                    if disk_write_iops_charts.datapoints:
                        disk_write_iops_rate = int(disk_read_iops / disk_write_iops_peak * 100) if disk_write_iops_peak > 0 else 0
                    else:
                        disk_write_iops_rate = 100
                    disk_write_iops_charts.append(disk_write_iops_rate)

                    disk_read_bps = disk_metrics_dict["read_Bps"]
                    if disk_read_bps > disk_read_bps_peak:
                        disk_read_bps_peak = disk_read_bps
                    disk_read_bps_charts.title = "Read : "+ f'{format_number(disk_read_bps)}/s (peak: {format_number(disk_read_bps_peak)}/s)'
                    if disk_read_bps_charts.datapoints:
                        disk_read_bps_rate = int(disk_read_bps / disk_read_bps_peak * 100) if disk_read_bps_peak > 0 else 0
                    else:
                        disk_read_bps_rate = 100
                    disk_read_bps_charts.append(disk_read_bps_rate)

                    disk_write_bps = disk_metrics_dict["write_Bps"]
                    if disk_write_bps > disk_write_bps_peak:
                        disk_write_bps_peak = disk_write_bps
                    disk_write_bps_charts.title = "Write : "+ f'{format_number(disk_write_bps)}/s (peak: {format_number(disk_write_bps_peak)}/s)'
                    if disk_write_bps_charts.datapoints:
                        disk_write_bps_rate = int(disk_write_bps / disk_write_bps_peak * 100) if disk_write_bps_peak > 0 else 0
                    else:
                        disk_write_bps_rate = 100
                    disk_write_bps_charts.append(disk_write_bps_rate)

                    network_in_bps = network_metrics_dict["in_Bps"]
                    if network_in_bps > network_in_bps_peak:
                        network_in_bps_peak = network_in_bps
                    network_in_bps_charts.title = "in : "+ f'{format_number(network_in_bps)}/s (peak: {format_number(network_in_bps_peak)}/s)'
                    if network_in_bps_charts.datapoints:
                        network_in_bps_rate = int(network_in_bps / network_in_bps_peak * 100) if network_in_bps_peak > 0 else 0
                    else:
                        network_in_bps_rate = 100
                    network_in_bps_charts.append(network_in_bps_rate)

                    network_out_bps = network_metrics_dict["out_Bps"]
                    if network_out_bps > network_out_bps_peak:
                        network_out_bps_peak = network_out_bps
                    network_out_bps_charts.title = "out : "+ f'{format_number(network_out_bps)}/s (peak: {format_number(network_out_bps_peak)}/s)'
                    if network_out_bps_charts.datapoints:
                        network_out_bps_rate = int(network_out_bps / network_out_bps_peak * 100)  if network_out_bps_peak > 0 else 0
                    else:
                        network_out_bps_rate = 100
                    network_out_bps_charts.append(network_out_bps_rate)

                    ui.display()
                    key_cmd = ''
                    with term.cbreak():
                        key = term.inkey(timeout=1)
                        if key:
                            if key.is_sequence:
                                if key.name == 'KEY_ESCAPE':
                                    key_cmd = "quit"
                            elif key.lower() == 'q':
                                    key_cmd = "quit"
                    if key_cmd == "quit":
                        print("\nStopping...")
                        break

            if str_output == '':
                time.sleep(0.1)

    except KeyboardInterrupt:
        print("Stopping...")
        print("\033[?25h")

    return 


if __name__ == "__main__":
    main()
    try:
        powermetrics_process.terminate()
        print("Successfully terminated powermetrics process")
    except Exception as e:
        print(e)
        powermetrics_process.terminate()
        print("Successfully terminated powermetrics process")

