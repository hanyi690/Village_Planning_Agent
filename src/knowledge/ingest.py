import os
from .rag import add_documents_to_vectorstore_to_vectorstore
from ..utils.logger import get_logger

logger = get_logger(__name__)

def ingest_text_folder(folder: str):
    """
    读取 folder 下所有 .txt 文件并写入向量库。
    """
    texts = []
    metas = []
    for root, _, files in os.walk(folder):
        for fn in files:
            if fn.lower().endswith(".txt"):
                path = os.path.join(root, fn)
                with open(path, "r", encoding="utf-8") as f:
                    txt = f.read()
                texts.append(txt)
                metas.append({"source": path})
                logger.info("读取并加入: %s", path)
    if not texts:
        logger.info("未找到 txt 文件: %s", folder)
        return {"status": "no_files"}
    res = add_documents_to_vectorstore(texts, metas)
    logger.info("写入向量库完成，数量: %s", res.get("count"))
    return res

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", "-f", required=True, help="包含文本文件的文件夹路径")
    args = parser.parse_args()
    ingest_text_folder(args.folder)
