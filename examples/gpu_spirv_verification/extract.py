#!/usr/bin/env python3

# Copyright (C) 
# SPDX-License-Identifier: MIT

import pathlib, os
import pandas as pd
import itertools
from functools import reduce
import re
import argparse
from typing import List
import json

target_types = ['block_size', 'total_space', 'shuffle_wg', 'shuffle_sg', 'wg_num', 'sg_num', 'sg_size', 'sg_stress_num']

expectations_csv_file = "expectations2.csv"

class ExtractUtils:
    @staticmethod
    def get_row_hw_vendor(value):
        global reg_c_bm_name
        r_bm_name = re.search(reg_c_bm_name, value)
        if r_bm_name is not None:
            return r_bm_name.group(1).replace("\\", "_").strip()
        return "unknown"
    
    @staticmethod
    def get_test_name(value: str) -> str:
        global reg_c_test_name
        r_name = re.search(reg_c_test_name, value)
        if r_name is not None:
            return r_name.group(1).strip()
        return value

    @staticmethod
    def highlight_fails(val, color: str):
        color = color if val == False or val == "FAIL" else 'black'
        return f'color: {color}'
    
    @staticmethod
    def load_expectations_into_df(df: pd.DataFrame) -> pd.DataFrame|None:
        def __align_with_test_names(row_value):
            # lookup corresponding 'annotated expectation' given a generated test
            try:
                if row_value.name in exp_df.index:
                    isnan = pd.isna(exp_df.loc[row_value.name, 'expected'])
                    return exp_df.loc[row_value.name, 'expected'] if not isnan else "NOT_FOUND"
                if "test_name_old_format" in exp_df.columns:
                    if row_value.name in exp_df['test_name_old_format'].values:
                        isnan = pd.isna(exp_df.loc[row_value.name, 'expected'])
                        return exp_df.loc[row_value.name, 'expected'] if not isnan else "NOT_FOUND"
            except KeyError as key:
                print(f"KeyError: '{key}' doest not exist in '{expectations_csv_file}' ... skipping")
            return
        
        script_path = os.path.abspath(os.path.dirname(__file__))
        csv_file_path = os.path.join(script_path, expectations_csv_file)
        
        if not pathlib.Path(csv_file_path).is_file():
            return
        
        exp_df = pd.read_csv(csv_file_path, comment="#", sep=',', engine="c")
        exp_df.set_index(('test_name'), inplace=True)

        # df['expectations'] = df.apply(__align_with_test_names, axis=1)
        # if isinstance(df.columns, pd.core.indexes.multi.MultiIndex):
        #     df = df.reindex(columns=[('expectations', '')] + sorted(df.columns.difference([('expectations','')]).tolist())).copy()
        # else:
        #     df = df.reindex(columns=[('expectations')] + sorted(df.columns.difference([('expectations')]).tolist())).copy()
        # return df

        new_df = df.copy() # about sparse and fragmeneted tables
        new_df['expectations'] = new_df.apply(__align_with_test_names, axis=1)
        if isinstance(new_df.columns, pd.core.indexes.multi.MultiIndex):
            new_df = new_df.reindex(columns=[('expectations', '')] + sorted(new_df.columns.difference([('expectations','')]).tolist())).copy()
        else:
            new_df = new_df.reindex(columns=[('expectations')] + sorted(new_df.columns.difference([('expectations')]).tolist())).copy()
        return new_df

def get_multi_from_dataframes(dfs: List[pd.DataFrame], use_columns: List[str] = None) -> pd.DataFrame:
    # def _load_expectations_into_df(df: pd.DataFrame) -> pd.DataFrame|None:
    #     def __align_with_test_names(row_value):
    #         # lookup corresponding 'annotated expectation' given a generated test
    #         try:
    #             if row_value.name in exp_df.index:
    #                 return exp_df.loc[row_value.name, 'expected']
    #             if "test_name_old_format" in exp_df.columns:
    #                 # print(row_value.name)
    #                 if row_value.name in exp_df['test_name_old_format'].values:
    #                     return exp_df.loc[row_value.name, 'expected']
    #         except KeyError as key:
    #             print(f"KeyError: '{key}' doest not exist in '{expectations_csv_file}' ... skipping")
    #         return
        
    #     script_path = os.path.abspath(os.path.dirname(__file__))
    #     csv_file_path = os.path.join(script_path, expectations_csv_file)
        
    #     if not pathlib.Path(csv_file_path).is_file():
    #         return
        
    #     exp_df = pd.read_csv(csv_file_path, comment="#", sep=',', engine="c")
    #     exp_df.set_index(('test_name'), inplace=True)

    #     df['expectations'] = df.apply(__align_with_test_names, axis=1)
    #     return df

    merged_df = None
    excluded_cols = ["perm_test_name"]
    multi_dfs = []
    for df in dfs:
        key_table = df['perm_test_name'].iloc[0]
        dff = df[[col for col in df.columns if not col in excluded_cols]]
        columns = pd.MultiIndex.from_product([[key_table], dff.columns], names=['Source', 'Values'])
        new_pd = pd.DataFrame(dff.values, columns=columns)
        # print(new_pd.columns.get_level_values('Values'))
        # exit()
        # new_pd.reset_index()
        new_pd.set_index((key_table,'test_name_reg'), inplace=True)
        multi_dfs.append(new_pd)
    
    # TODO: support columns concat from same gpu test which will lead with non-unique jobs
    concat_df = pd.concat(multi_dfs, axis=1)
    
    # print(concat_df.head())
    # stacked_df = concat_df.stack(level='Source')
    # print(stacked_df.head())
    # stacked_df.set_index(('test_name_reg'), inplace=True) # TODO: this is now working ...
    # print(stacked_df.head())
    # unstacked_df = stacked_df.unstack(level='test_name_reg')
    # print(unstacked_df.columns)
    # exit()
    
    for idx, row in concat_df.iterrows(): 
        for cols, value in row.items():
            if "test_name" in cols:
                assert idx == ExtractUtils.get_test_name(value)

    concat_df = ExtractUtils.load_expectations_into_df(concat_df)
    
    exported_standalone_cols = ['expectations']
    exported_sub_cols = ['status'] if use_columns is None else use_columns
    
    if not isinstance(exported_sub_cols, list):
        exported_sub_cols = [exported_sub_cols]

    sub_cols = concat_df.columns.get_level_values('Values')
    standalone_cols = concat_df.columns
    
    # we get columns in a list form [('PrimaryColumn', 'SubColumn')]
    # standalone columns are expressed as: [('PrimaryColumn', '')], e.g. ('expectations', '')
    # sub-columns with multi-index as expressed as: [('PrimaryColumn', 'SubColumn')], e.g. ('AMD_test_whatever', 'status')
    sel_standalone_cols = [c for c in standalone_cols if c[0] in exported_standalone_cols]
    sel_sub_cols = concat_df.columns[concat_df.columns.get_level_values('Values').isin(exported_sub_cols)].tolist()
    
    df_by_status = concat_df.loc[:, sel_standalone_cols + sel_sub_cols]

    return df_by_status
def get_results_from_dataframes(dfs: List[pd.DataFrame], **_kwargs) -> (str, str, str):   
    def _raw_capture_json_curly_brackets(raw_json: str) -> str:
        raw_json_result = []
        curly_stack = []
        curly_start = 0
        curly_end = 0

        for c_pos, char in enumerate(raw_json):
            if char == '{':
                if len(curly_stack) == 0:
                    # new starting group detected
                    curly_start = c_pos
                curly_stack.append(char)
            elif char == '}':
                curly_stack.pop()
                if len(curly_stack) == 0:
                    # end of group detected, finish and capture
                    curly_end = c_pos
                    raw_json_result.append(raw_json[curly_start:curly_end+1])
        
        return raw_json_result

    filtering = _kwargs["filter"] if "filter" in _kwargs.keys() else None
    
    reg_filtering_test_name = fr'## gen\\(.*{(".*" if filtering is None else filtering)}.*)' # raw + f-string format 
    filtering_test_name_pattern = re.compile(reg_filtering_test_name, re.MULTILINE)
    
    results = []

    cols_filter = ["test_name"] + target_types + ["n_failed", "n_total", "failed_ratio"]

    if not isinstance(dfs, list):
        dfs = [dfs]

    # pivoted_dfs = reduce(lambda inplace: inplace.pivot(index='test_name', columns='perm_test_name', values='status'), dfs)
    # pivoted_df = merged_df.pivot(index='test_name', columns='perm_test_name', values='status').sort_values(by='test_name', ascending=True)

    # merged_df = reduce(lambda left, right: pd.merge(left, right, on='test_name', how='outer'), dfs)
    # pivoted_df = merged_df.pivot(index='test_name', columns='perm_test_name', values='status').sort_values(by='test_name', ascending=True)

    for df in dfs:
        # new_results = { "test_name" : "", "test_type" : "", "headers" : [], "data" : [], "timestamps" : [], "global_counts" : { "total" : "", "values" : {"00", ...} }, "status" : { "n_fails" : None, "n_checks" : None, "msg_status" : None } }
        
        dff = df[cols_filter]

        for row in df.itertuples():
            new_results = {}
            new_results["test_name"] = ExtractUtils.get_test_name(row.test_name)
            new_results["test_type"] = row.test_type
            new_results["headers"] = []
            new_results["data"] = []
            new_results["timestamps"] = []
            new_results["global_counts"] = { "total" : int(row.n_total), "values" : {} }
            new_results["status"] = { "n_fails" : int(row.n_failed), "n_checks" : int(row.n_total), "msg_status" : row.status }

            hw_vendor = row.hw_vendor
            failed_ratio = row.failed_ratio
            raw_info = row.info

            for raw_json in _raw_capture_json_curly_brackets(raw_info):
                json_info = json.loads(raw_json)
                if "total" in json_info.keys():
                    try:
                        assert new_results["global_counts"]["total"] == json_info["total"], f"Error on {hw_vendor}/{new_results['test_name']}"
                        new_results["global_counts"]["values"] = json_info["values"]

                        check_total = 0
                        for k, v in json_info["values"].items():
                            check_total += v

                        assert new_results["global_counts"]["total"] == check_total, f"Error on {hw_vendor}/{new_results['test_name']}"
                        assert new_results["status"]["n_checks"] == check_total, f"Error on {hw_vendor}/{new_results['test_name']}"
                    except:
                        if "iriw" in new_results['test_name']:
                            pass
                        else:
                            print("ERROR!!")
                            assert False


            results.append(new_results)

    comments_msg = ""
    headers_msg = ""
    content_msg = []
    if (len(results)):
        
        comments_msg += f"# PASSED\n"
        # for exp in experiments["passed"].keys():
        #     content_msg += f'{experiments["passed"][exp]}\n'

        comments_msg += "# WEAK\n"
        # for exp in experiments["weak"].keys():
        #     content_msg += f'{experiments["weak"][exp]}\n'

        csv_headers = "{test_name};{test_type};{status};{wb_header};{n_failed};{n_total};{failed_ratio};{info}".format(
            test_type="test_type", test_name="test_name", status="status",
            wb_header="wb_header", n_failed="n_failed", n_total="n_total", failed_ratio="failed_ratio", info="info")

        headers_msg += f"{csv_headers}\n"

        for r in results:
            msg = ""

            test_name = r["test_name"]
            test_type = r["test_type"]
            status=r["status"]["msg_status"]
            relaxed_values=r["status"]["n_fails"]
            n_total_checks=r["status"]["n_checks"]
            failed_ratio=relaxed_values/n_total_checks
            
            relaxed_header=None #TODO: get from expectations
        
            txt = "{test_name};{test_type};{status};'{wb_header};{n_failed};{n_total};{failed_ratio};\"{wb_header}\" {n_failed}/{n_total}".format(
                test_name=test_name,
                test_type=test_type,
                status=status,
                wb_header=relaxed_header,
                n_failed=relaxed_values,
                n_total=n_total_checks,
                failed_ratio=failed_ratio)

            msg += f"{txt}\n"
            content_msg.append(msg)

    return comments_msg, headers_msg, content_msg


def generate_output_folder(output_dir: str) -> pathlib.Path:
    script_path = os.path.abspath(os.path.dirname(__file__))
    proposed_output_path = os.path.join(script_path, output_dir)
    counter = 1
    while pathlib.Path(proposed_output_path).is_dir():
        proposed_output_path = f"output_dir_{counter}"
        counter += 1

    os.makedirs(os.path.join(proposed_output_path, "csv"))
    os.makedirs(os.path.join(proposed_output_path, "multi"))
    return pathlib.Path(proposed_output_path).resolve()

def extract_global_dataframe(
    csv_pathnames: List[pathlib.Path],
    nan_replace: bool = True,
    **kwargs
) -> pd.DataFrame:
    dataframes = [df for csv_file in csv_pathnames
        if (df := pd.read_csv(csv_file.resolve(), sep=";", comment="#", keep_default_na=nan_replace, engine=kwargs.get("engine", "python")).dropna()) is not None]
    return pd.concat(dataframes)

if __name__ == "__main__":
    parser = argparse.ArgumentParser("Data extractor")
    parser.add_argument('files', metavar='F', type=str, nargs='+', help='Given list of file paths separated by empty space(s)')
    parser.add_argument('-o', '--output', required=False, metavar='OUTPUT_PATH', type=str, default='out', help='Path to the output folder to stored extracted data (default_path = ./out)')
    parser.add_argument('-l', '--list', required=False, action='store_true', help="Show list of extracted remote platforms")
    parser.add_argument('--prefix', type=str, metavar='PREFIX', default="spirv-empirical-default", help="exclude PREFIX from the test name (default = 'spirv-empirical-default')")
    parser.add_argument('-n', '--dryrun', required=False, action='store_true', help="dryrun execution")
    parser.add_argument('-V', '--version', action='version', version='%(prog)s v0.1')
    args = parser.parse_args()

    paths = args.files
    output_dir = args.output
    prefix_test_name = args.prefix
    do_listing = args.list

    reg_c_test_name = re.compile(fr"{prefix_test_name}(\\.+)$")
    reg_c_bm_name = re.compile(fr"benchkit\\(.+)\\{prefix_test_name}")

    print(f"Using paths: {paths}")

    # paths = [
    #     '/home/arnau/benchkit-acasadevall/examples/gpu_spirv_verification/results/0/benchmark_20250401_100114.csv',
    #     '/home/arnau/benchkit-acasadevall/examples/gpu_spirv_verification/results/1/benchmark_20250401_100114.csv',
    #     '/home/arnau/benchkit-acasadevall/examples/gpu_spirv_verification/results/2/benchmark_20250401_100114.csv'
    # ]

    # paths = [
    #     '/home/arnau/benchkit-acasadevall/examples/gpu_spirv_verification/results/benchmark_node91_gpu-research-nvidia_cartesian_campaign_20250401_155305_382990.csv',
    #     '/home/arnau/benchkit-acasadevall/examples/gpu_spirv_verification/results/benchmark_node91_gpu-research-intel_cartesian_campaign_20250401_160419_780801.csv',
    #     '/home/arnau/benchkit-acasadevall/examples/gpu_spirv_verification/results/benchmark_node91_gpu-research-amd_cartesian_campaign_20250401_160043_962599.csv',
    #     '/home/arnau/benchkit-acasadevall/examples/gpu_spirv_verification/results/benchmark_node91_gpu-research-amd_cartesian_campaign_20250401_155857_951309.csv'
    # ]

    pathlibs = [ pathlib.Path(p) for p in paths ]

    df_data = extract_global_dataframe(pathlibs, engine="c") # dropna
    df_data["hw_vendor"] = df_data["test_name"].apply(ExtractUtils.get_row_hw_vendor) # apply new column `hw_vendor`
    df_data['test_name_reg'] = df_data["test_name"].apply(ExtractUtils.get_test_name)
    df_data["perm_test_name"] = None
    df_data['failed_ratio'] = df_data['failed_ratio'].apply(lambda value: f"{value*100:.4f}")
    df_data['n_failed'] = df_data['n_failed'].apply(lambda value: int(value))
    df_data['n_total'] = df_data['n_total'].apply(lambda value: int(value))

    cols = df_data.columns
    hostnames = df_data['hostname'].unique()
    
    data = {h: [] for h in hostnames}
    perm = {h: [] for h in hostnames}
    hw_vendors = {h: [] for h in hostnames}

    total_hw_vendors = 0
    for h in hostnames:
        dff_hostname = df_data[(df_data['hostname']==h)]
        for hw in dff_hostname['hw_vendor'].unique():
            hw_vendors[h].append(hw)
            total_hw_vendors += 1

    ## Listing hardware found
    print(f"Total Hardware found = {total_hw_vendors}")
    for h in hostnames:
        print(f"Machine: {h}")
        for hw in hw_vendors[h]:
            print(f"  > Hardware: {hw}")

    if do_listing:
        exit(0)

    list_of_tests = {}
    for h in hostnames:
        dff_hostname = df_data[(df_data['hostname']==h)]
        list_of_tests[h] = dff_hostname['test_name'].unique()

    for h in hostnames:
        data[h] = {hw: [] for hw in hw_vendors[h]}

    
    for h in hostnames:
        perm[h] = {t: df for t in target_types if (df := df_data[df_data['hostname']==h][t].unique()) is not None}
    
    permutations = None
    for h in hostnames:
        for hw in hw_vendors[h]:
            dff_hostname = df_data[(df_data['hostname']==h) & (df_data['hw_vendor']==hw)]
            iter_permutations = list(itertools.product(*[perm[h][t] for t in target_types]))
            
            # apply permutation filters to new DataFrame `dff_hostname`
            for perm_id, iter_p in enumerate(iter_permutations):
                str_names = "_".join([str(i_p) for i_p in iter_p])
                filter_cond = True
                for t, value in zip(target_types, iter_p):
                    filter_cond &= (dff_hostname[t] == value)
                dff = dff_hostname[filter_cond].copy() # get new DataFrame copy()

                perm_test_name = f"{hw}_{perm_id}_{str_names}"
                # df_data.loc[filter_cond, 'perm_test_name'] = perm_test_name
                dff['perm_test_name'] = perm_test_name
                dff['failed_ratio'] = dff['failed_ratio'].apply(lambda value: f"{value}%")

                data[h][hw].append({
                        "hostname"  : h,
                        "hw_vendor" : hw,
                        "test_name" : perm_test_name,
                        "data"      : dff
                    })

        # print("perm: %d" % (len(iter_permutations)))
        # print(iter_permutations)
    
    # now data is separated as
    # hostname/hw_vendor -> permutation/combination

    abs_output_path = generate_output_folder(output_dir)

    dffs = [d["data"] for h in data.keys() for hw in data[h].keys() for d in data[h][hw]]
    df_by_status = get_multi_from_dataframes(dffs, use_columns=['status', 'failed_ratio'])
    df_by_status.to_csv(abs_output_path / "multi" / "multiple.csv", index=True)
    df_by_status.to_html(abs_output_path / "multi" / "multiple.html", index=True)

    agg_fails = {}
    merged_fails = []
    multi_fails_dfs =[]
    for h in data.keys():
        for hw in data[h].keys():
            total_fail_checks = 0
            for d_id, d in enumerate(data[h][hw]):
                tn = d["test_name"]
                df = d["data"]

                key_table = df['perm_test_name'].iloc[0]

                mask = df["n_failed"] > 0
                dff = df[mask].copy()
                
                dff = dff[[c for c in dff.columns if c in ["test_name_reg", "n_failed", "n_total", "failed_ratio"]]]
                merged_fails.append(dff)

                columns = pd.MultiIndex.from_product([[key_table], dff.columns], names=['Source', 'Values'])
                new_pd = pd.DataFrame(dff.values, columns=columns)
                # print(new_pd.columns.get_level_values('Values'))
                new_pd.set_index((key_table,'test_name_reg'), inplace=True)
                multi_fails_dfs.append(new_pd)

                total_fail_checks = mask.sum()
                print(f"{h}::{hw} ({tn})")
                print(f" - Total fails: {total_fail_checks}")

                if "hw" in agg_fails.keys():
                    agg_fails[hw] += total_fail_checks
                else:
                    agg_fails[hw] = total_fail_checks

    print(agg_fails)
    
    concat_fails_df = pd.concat(multi_fails_dfs, axis=1)
    concat_fails_df = ExtractUtils.load_expectations_into_df(concat_fails_df)
    print(concat_fails_df.head())
    # print(concat_fails_df.columns)
    # exit()
    styled_df = concat_fails_df.style.applymap(lambda val: ExtractUtils.highlight_fails(val, color='red'), subset=concat_fails_df.columns) \
        .set_table_styles([
            # Table style
            {'selector': 'table',
            'props': [
                ('border-collapse', 'collapse'),
                ('width', '100%'),
                ('font-family', 'Arial, sans-serif'),
                ('font-size', '14px')
            ]},

            # Header style
            {'selector': 'th',
            'props': [
                ('background-color', '#f2f2f2'),
                ('color', '#333'),
                ('text-align', 'center'),
                ('padding', '8px'),
                ('border', '1px solid #ccc')
            ]},

            # Cell style
            {'selector': 'td',
            'props': [
                ('text-align', 'center'),
                ('padding', '8px'),
                ('border', '1px solid #ccc')
            ]},

            # Index style (if shown)
            {'selector': '.row_heading',
            'props': [
                ('font-weight', 'bold'),
                ('color', '#555'),
                ('border', '1px solid #ccc'),
                ('background-color', '#fafafa')
            ]}
        ]).set_table_styles([
            {'selector': 'tbody tr:nth-child(even)',
            'props': [('background-color', '#f9f9f9')]}
        ], overwrite=False)
    
    styled_df.to_html(abs_output_path / "multi" / "multi_fails_dfs_2.html", sparse_columns=True)
    concat_fails_df.to_html(abs_output_path / "multi" / "multi_fails_dfs.html", index=True)
    concat_fails_df.to_csv(abs_output_path / "multi" / "multi_fails_dfs.csv", index=True)
    concat_fails_df.to_excel(abs_output_path / "multi" / "multi_fails_dfs.xlsx", engine='openpyxl', index=True)

    for h in data.keys():
        for hw in data[h].keys():
            for d_id, d in enumerate(data[h][hw]):
                tn = d["test_name"]
                df = d["data"]
                # cols_filter = ["test_name"] + target_types + ["n_failed", "n_total", "failed_ratio"]
                # dff = df[cols_filter]

                file_path_benchkit_csv = f"{h}_{hw}_{d_id}.csv"
                file_path_raw_csv = f"raw.{h}_{hw}_{d_id}.csv"
                with open(abs_output_path / file_path_benchkit_csv, 'w') as f:
                    f.write(f"# {tn}\n")
                    for t in target_types:
                        f.write(f"# {t}: {df[t].unique()}\n")
                df.to_csv(abs_output_path / file_path_benchkit_csv, mode='a', index=False)

                # get data in old format
                comments_msg, headers_msg, content_msg = get_results_from_dataframes(df)

                with open(abs_output_path / "csv" / file_path_raw_csv, 'w') as f:
                    f.write(f"# {tn}\n")
                    for t in target_types:
                        f.write(f"# {t}: {df[t].unique()}\n")
                    f.write(comments_msg)
                    f.write(headers_msg)
                    for c in content_msg:
                        f.write(c)

    print(f"Extracted files strored in: {abs_output_path}")
