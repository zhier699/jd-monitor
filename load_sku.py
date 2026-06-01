"""
从桌面 sku.xls 动态加载各品牌合作 SKU 列表。

Excel 格式说明（Sheet1）：
  - 4 个品牌并排排列，每品牌有"是否合作品"列（是/否）
  - 仅"是"的 SKU 纳入监控
合作时间 sheet：
  - 含科沃斯型号名，用于补充 Sheet1 中无型号的品牌

用法（在 run_*.py 中）：
    from load_sku import merge_projects_with_excel
    cfg.PROJECTS = merge_projects_with_excel(cfg.PROJECTS)
"""
from pathlib import Path
import xlrd

# Excel 文件默认在代码目录的上一级（桌面）
_DEFAULT_XLS = Path(__file__).parent.parent / "sku.xls"

# Sheet1 各品牌列位置（行0=品牌名，行1=表头，行2起=数据）
_BRAND_COLS = {
    "海信":   {"model": 1,    "sku": 2,  "flag": 3},
    "VIDDA":  {"model": None, "sku": 6,  "flag": 7},
    "云鲸":   {"model": None, "sku": 11, "flag": 12},
    "科沃斯": {"model": None, "sku": 16, "flag": 17},
}


def load_sku_from_excel(xls_path=None) -> dict[str, list[dict]]:
    """
    读取 Excel，返回 {品牌名: [{"sku": "...", "name": "..."}]}。
    品牌名与 projects.json 的 name 字段一致。
    """
    path = Path(xls_path) if xls_path else _DEFAULT_XLS
    if not path.exists():
        print(f"⚠️ 未找到 SKU 表格: {path}，使用 projects.json 原有配置")
        return {}

    try:
        wb = xlrd.open_workbook(str(path), encoding_override="gbk")
    except Exception as e:
        print(f"⚠️ 读取 Excel 失败: {e}，使用 projects.json 原有配置")
        return {}

    # ── 从"合作时间"sheet 建 sku→型号 映射（含科沃斯型号名）──────
    sku_to_model: dict[str, str] = {}
    try:
        sh_time = wb.sheet_by_name("合作时间")
        for r in range(2, sh_time.nrows):          # 行0=品牌名，行1=表头
            sku_raw = str(sh_time.cell_value(r, 2)).replace(".0", "").strip()
            model   = str(sh_time.cell_value(r, 1)).strip()
            if sku_raw and sku_raw not in ("/", "nan", "") and model:
                sku_to_model[sku_raw] = model
    except Exception:
        pass  # 没有该 sheet 也不影响主流程

    # ── 从 Sheet1 提取各品牌合作 SKU ──────────────────────────────
    try:
        sh1 = wb.sheet_by_name("Sheet1")
    except Exception as e:
        print(f"⚠️ 找不到 Sheet1: {e}")
        return {}

    result: dict[str, list[dict]] = {}
    for brand, cols in _BRAND_COLS.items():
        ci_model = cols["model"]
        ci_sku   = cols["sku"]
        ci_flag  = cols["flag"]
        skus: list[dict] = []

        for r in range(2, sh1.nrows):
            try:
                flag    = str(sh1.cell_value(r, ci_flag)).strip()
                sku_raw = str(sh1.cell_value(r, ci_sku)).replace(".0", "").strip()
            except IndexError:
                continue

            if flag != "是" or not sku_raw or sku_raw in ("/", "nan", ""):
                continue

            # 型号优先级：Sheet1 型号列 → 合作时间映射 → SKU 号兜底
            if ci_model is not None:
                model = str(sh1.cell_value(r, ci_model)).strip()
            else:
                model = ""
            name = model or sku_to_model.get(sku_raw, sku_raw)

            skus.append({"sku": sku_raw, "name": name})

        result[brand] = skus
        print(f"📋 [SKU表格] {brand}：{len(skus)} 个合作SKU")

    return result


def merge_projects_with_excel(projects: list, xls_path=None) -> list:
    """
    将 projects.json 中的 projects 与 Excel SKU 合并。
    - webhook / owner 保持不变（来自 projects.json）
    - skus 替换为 Excel 中"是否合作品=是"的列表
    - 若 Excel 缺失或某品牌不在 Excel 中，回退到 projects.json 原有 skus
    """
    sku_data = load_sku_from_excel(xls_path)
    if not sku_data:
        return projects  # Excel 读取失败，原样返回

    merged = []
    for p in projects:
        excel_skus = sku_data.get(p["name"])
        if excel_skus is not None:
            merged.append({**p, "skus": excel_skus})
        else:
            merged.append(p)  # 该品牌不在 Excel 中，保留原 skus
    return merged
