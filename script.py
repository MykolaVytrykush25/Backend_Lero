files = ["Users/views.py", "Main/views.py", "Proxy/views.py"]
with open("static/locales.json", "r", encoding="utf-8") as fj:
    fjr = fj.read()
    with open("messages.txt", "w", encoding="utf-8") as fw:
        for file in files:
                with open(file, "r", encoding="utf-8") as f:
                    msgs = f.read().split('"message": "')
                    for msg in msgs:
                        msg_text = msg.split('"')[0]
                        if msg_text not in fjr:
                            fw.write("\n"+msg_text)
    fw.close()