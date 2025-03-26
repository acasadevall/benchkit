import csv
import re
import json
import os

reg_dev_iter = re.compile('D_Iter([0-9]+)')

def has_relaxed_values(test_type, data):
    if test_type in legend_annotations.keys() and isinstance(data, dict):
        if 'r' in legend_annotations[test_type].keys():
            for v in legend_annotations[test_type]['r']:
                if v in data.keys():
                    return sum(data[v]) > 0
    
    return False

def get_desc_type(test_type, legend):
    if test_type in legend_annotations.keys():
        for key in legend_annotations[test_type].keys():
            if legend in legend_annotations[test_type][key]:
                if key == 's':
                    return 'sequential'
                if key == 'r':
                    return 'relaxed'
                if key == 'i':
                    return 'interleaving'
    return None

def get_marker(test_type, legend):
    if test_type in legend_annotations.keys():
        for key in legend_annotations[test_type].keys():
            if legend in legend_annotations[test_type][key]:
                if key == 'r':
                    return 'x'
                if key == 'i':
                    return '.'
    return None

def get_line(test_type, legend):
    if test_type in legend_annotations.keys():
        for key in legend_annotations[test_type].keys():
            if legend in legend_annotations[test_type][key]:
                if legend != legend_annotations[test_type][key][-1]:
                    # meaning we have more than one, identify with a dashed a line
                    return "--"
    return "-"

def get_color(test_type, legend):
    if test_type in legend_annotations.keys():
        for key in legend_annotations[test_type].keys():
            if legend in legend_annotations[test_type][key]:
                return legend_annotations["color"][key]
    return 'red'

legend_annotations = {
    "color" : {
        's' : 'orange', # sequential
        'i' : 'blue', # interleaving
        'r' : 'green' # relaxed
    },
    "mp" : {
        's' : ["00", "11"],
        'i' : ["01"],
        'r' : ["10"],
    },
    "sb" : {
        's' : ["01", "10"],
        'i' : ["11"],
        'r' : ["00"]
    },
    "lb" : {
        's' : ["01", "10"],
        'i' : ["00"],
        'r' : ["11"]
    },
    "default" : {}
}

def parse_output_to_results(command_output, **_kwargs):

    begin_pattern = re.compile(r'^[ ]*,[ ]*BEGIN([ ]+.*)?\n', re.MULTILINE)
    end_pattern = re.compile(r'^[ ]*,[ ]*END([ ]+.*)?', re.MULTILINE)

    filtering = _kwargs["filter"] if "filter" in _kwargs.keys() else None
    
    reg_filtering_test_name = fr'## gen\\(.*{(".*" if filtering is None else filtering)}.*)' # raw + f-string format 
    filtering_test_name_pattern = re.compile(reg_filtering_test_name, re.MULTILINE)

    begin_markers = re.finditer(begin_pattern, command_output)
    end_markers = re.finditer(end_pattern, command_output)
    
    results = []

    for (m1, m2) in zip(begin_markers, end_markers):

        new_results = { "test_name" : "", "test_type" : "", "headers" : [], "data" : [], "timestamps" : [], "global_counts" : { "total" : "", "values" : {} }, "status" : { "n_fails" : None, "n_checks" : None, "msg_status" : None } }
        
        # get content between BEGIN/END markers
        content = command_output[m1.end():m2.start()]
        
        ## Look for test name
        m_test_name = re.search(filtering_test_name_pattern, content)
        test_found = False
        if m_test_name is not None:
            t = m_test_name.group(1)
            t = t.replace("\\", "_")
            new_results["test_name"] = t
            test_found = True

        if test_found == False:
            continue

        ## Look for timestamps
        m_timestamps = re.finditer('## Timestamp Record,([0-9]+),(.*)', content)
        
        for m in m_timestamps:
            k = m.group(1)
            v = m.group(2)
            new_results["timestamps"].append([float(i) for i in v.strip().split(',')])

        ## Look for global coutings
        counts_begin_marker = re.finditer(r'## Global counts \(total = ([0-9]+).*\n', content, re.MULTILINE)
        counts_end_marker = re.finditer('## Total valid ids.*,([0-9]+).*$', content, re.MULTILINE)

        total_counts = 0
        total_valid_counts = 0
        counts_content = ""
        for (begin, end) in zip(counts_begin_marker, counts_end_marker):
            total_counts = int(begin.group(1))
            total_valid_counts = int(end.group(1))
            counts_content = content[begin.end():end.start()]

        new_results["global_counts"]["total"] = total_counts

        counts_content = counts_content.strip().split('\n')
        assert len(counts_content) == 2

        m_counts_headers = re.finditer('([0-9]+),', counts_content[0])
        m_counts_values = re.finditer('([0-9]+),', counts_content[1])

        for (m_header, m_values) in zip(m_counts_headers, m_counts_values):
            header = m_header.group(1)
            value = int(m_values.group(1))
            new_results["global_counts"]["values"][header] = value

        ## Look for fails/checks/status
        # ;## Fails/Checks;0;5222400;PASS
        m_status = re.finditer(r'## Fails/Checks,([0-9]+),([0-9]+),([\w]+)', content)

        for m in m_status:
            n_fails = int(m.group(1))
            n_checks = int(m.group(2))
            status = m.group(3)
            new_results["status"] = { "n_fails" : n_fails, "n_checks" : n_checks, "msg_status" : status }

        ## Look for countings per device iteration
        m11 = re.search('## Evaluation per Kernel iterations', content, re.MULTILINE)
        m22 = re.search('## Global counts', content, re.MULTILINE)
        sub_content = content[m11.end():m22.start()].strip().split('\n')
        
        # fix headers backward compatibility issue (workaround)
        headers = [h for h in sub_content[0].split(',') if h != "HasError" and h != "ErrMsg"]
        # headers = ["HasError"] + ["ErrMsg"] + headers

        new_results["headers"] = headers
        new_results["data"] = sub_content[1:]

        assert len(new_results["headers"]) == len(new_results["data"][0].split(','))

        # print(len(new_results["headers"]))
        # print(len(new_results["data"][0].split(',')))

        if "_mp_" in new_results["test_name"]:
            new_results["test_type"] = "mp"
        elif "_sb_" in new_results["test_name"]:
            new_results["test_type"] = "sb"
        elif "_lb_" in new_results["test_name"]:
            new_results["test_type"] = "lb"
        else:
            new_results["test_type"] = "unknown"

        results.append(new_results)

    print("# Found: {}".format(len(results)))

    if len(results) == 0:
        return []

    return results



def my_parser(csv_input, prefix=None, is_first_call=True):
    r = None
    # with open(filename, mode='r', newline='', encoding='utf-8') as csvfile:
    #     # considering adding ` quotechar='"' ` in case we have embedded newlines inside fields
    #     # e.g., "John Doe","123 Main St\nApt 4","Some other field"
    #     rows = csv.reader(csvfile, delimiter=';')
    #     r = '\n'.join([','.join(r) for r in rows])

    r = csv_input.replace(';',',')
    
    test_results = parse_output_to_results(r, filter=None)

    prefix_test = "spirv-empirical-default" if prefix is None else prefix

    reg_c_filter_list = re.compile(fr'^({prefix_test})(_.*)')
    reg_c_test_name = re.compile(r'(.*_(.*)-\[(.*)\]-\[(.*)\])(.*)')
    reg_c_test_name2 = re.compile(r'(.*_(.*)-\[(.*)\])(.*)') # load-[wg]-av-sDv
    reg_c_test_name3 = re.compile(r'(.*_(.*))(_[^_]+.*)$') # semantics_FdvAcqrelSun
    experiments = { "all" : {}, "passed" : {}, "weak" : {} }
    
    for n_test, test in enumerate(test_results):
        test_name = test["test_name"]
        test_type = test["test_type"]
        global_counts = test["global_counts"]
        status = test["status"]

        global_counts_values = test["global_counts"]["values"]
        
        test_type_reg = test_type
        inter_intra = ""
        sb_wg = ""

        # substract the "prefix" if exists, e.g. <prefix_test_name>\atomic\lb\mo\lb-[diff-wg]-[sb-sb]-rel-acq-rx-rx
        prefix_m = re.search(reg_c_filter_list, test_name)
        if prefix_m is not None:
            test_name = prefix_m.group(2)

        m = re.search(reg_c_test_name, test_name)
        if m is None:
            m2 = re.search(reg_c_test_name2, test_name)
            if m2 is None:
                m3 = re.search(reg_c_test_name3, test_name)
                if m3 is None:
                    continue
                else:
                    test_name_win = m3.group(1).replace("_", "\\") + m3.group(3)
                    test_name = test_name_win
                    test_type_reg = m3.group(2)
            else:
                test_name_win = m2.group(1).replace("_", "\\") + m2.group(4)
                test_name = test_name_win
                sb_wg = m2.group(3)
                test_type_reg = m2.group(2)

        else:
            test_name_win = m.group(1).replace("_", "\\") + m.group(5)
            test_name = test_name_win
            inter_intra = m.group(3)
            sb_wg = m.group(4)
            test_type_reg = m.group(2)

        is_self_test = True if "diff" in inter_intra and "wg" in sb_wg else False
        test_type_s = test_type_reg + "/self_test" if is_self_test else test_type_reg

        v = 0
        for t in global_counts_values.keys():
            v += global_counts_values[t]

        assert v == test["global_counts"]["total"]

        global_counts_values_ratio = {}
        for t in global_counts_values.keys():
            total = test["global_counts"]["total"] if test["global_counts"]["total"] > 0 else 1
            global_counts_values_ratio[t] = f'{100*global_counts_values[t]/total:.4f}%'

        relaxed_header = "N/A"
        relaxed_values = None
        n_total_checks = None
        
        if test_type != "unknown":
            relaxed_header = legend_annotations[test_type]['r'][0]
            relaxed_values = global_counts_values[relaxed_header]
            n_total_checks = test["global_counts"]["total"] if test["global_counts"]["total"] > 0 else 1

        elif test_type == "unknown" and status["msg_status"] is not None:
            relaxed_values = status["n_fails"]
            n_total_checks = status["n_checks"] if status["n_checks"] > 0 else 1

        else:
            relaxed_values = 0
            n_total_checks = 1
        
        num_status = "PASS" if relaxed_values == 0 else "FAIL"
        msg_status = status["msg_status"] if status["msg_status"] is not None else num_status

        txt = "{test_name};{test_type};{status};'{wb_header};{n_failed};{n_total};{failed_ratio};\"{wb_header}\" {n_failed}/{n_total}".format(
            test_type=test_type_s, test_name=test_name, status=msg_status,
            wb_header=relaxed_header, n_failed=relaxed_values, n_total=n_total_checks, failed_ratio=relaxed_values/n_total_checks)

        json.dumps(test["global_counts"])
        txt += " " + json.dumps(test["global_counts"])
        txt += " " + json.dumps(global_counts_values_ratio)

        if relaxed_values:
            experiments["weak"][test_name] = txt
        else:
            experiments["passed"][test_name] = txt
        experiments["all"][test_name] = txt
    
    csv_headers = "{test_name};{test_type};{status};{wb_header};{n_failed};{n_total};{failed_ratio};{info}".format(
            test_type="test_type", test_name="test_name", status="status",
            wb_header="wb_header", n_failed="n_failed", n_total="n_total", failed_ratio="failed_ratio", info="info")

    content_msg = ""

    if (len(test_results)):
        # content_msg += f"# PASSED\n"
        for exp in experiments["passed"].keys():
            content_msg += f'{experiments["passed"][exp]}\n'

        # content_msg += "# WEAK"
        for exp in experiments["weak"].keys():
            content_msg += f'{experiments["weak"][exp]}\n'
    
    return csv_headers, content_msg