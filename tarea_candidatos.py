import os,re,time,smtplib,sqlite3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

DRY_RUN=True
SINGLE_SINK_EMAIL=None
SMTP_HOST="smtp.gmail.com"
SMTP_PORT=587
SENDER_EMAIL=os.getenv("SENDER_EMAIL") or "tu_correo@gmail.com"
SENDER_APP_PASSWORD=os.getenv("SENDER_APP_PASSWORD") or "APP_PASSWORD"
EMAIL_SUBJECT="Información de tu postulación"
RATE_SLEEP=0.4
RETRIES=1
CSV_PATH="candidates.csv"
DB_PATH="candidates.db"
TABLE="candidates"
EMAIL_RE=re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def load_csv(path=CSV_PATH):
    df=pd.read_csv(path,sep=";",engine="python")
    df=df.rename(columns={
        "First Name":"first_name",
        "Last Name":"last_name",
        "Email":"email",
        "Country":"country",
        "Application Date":"application_date",
        "YOE":"yoe",
        "Seniority":"seniority",
        "Technology":"technology",
        "Code Challenge Score":"code_challenge_score",
        "Technical Interview Score":"technical_interview"
    })
    df["first_name"]=df["first_name"].astype("string").str.strip()
    df["last_name"]=df["last_name"].astype("string").str.strip()
    df["email"]=df["email"].astype("string").str.strip().str.lower()
    df["country"]=df["country"].astype("string").str.strip()
    df["seniority"]=df["seniority"].astype("string").str.strip()
    df["technology"]=df["technology"].astype("string").str.strip()
    df["application_date"]=pd.to_datetime(df["application_date"],errors="coerce",utc=True)
    df["yoe"]=pd.to_numeric(df["yoe"].astype("string").str.replace(",",".",regex=False),errors="coerce")
    df["code_challenge_score"]=pd.to_numeric(df["code_challenge_score"],errors="coerce")
    df["technical_interview"]=pd.to_numeric(df["technical_interview"],errors="coerce")
    df["email_valid"]=df["email"].fillna("").apply(lambda x: bool(EMAIL_RE.match(x)))
    return df

DDL=f"""
CREATE TABLE IF NOT EXISTS {TABLE}(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 first_name TEXT,last_name TEXT,email TEXT,country TEXT,application_date TEXT,
 yoe REAL,seniority TEXT,technology TEXT,code_challenge_score REAL,technical_interview REAL,email_valid INTEGER
);
"""
INDEXES=[
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_email ON {TABLE}(email);",
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_country ON {TABLE}(country);",
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_tech ON {TABLE}(technology);",
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_appdate ON {TABLE}(application_date);"
]

def save_sqlite(df):
    con=sqlite3.connect(DB_PATH)
    with con:
        con.execute(DDL)
        con.execute(f"DELETE FROM {TABLE};")
        df2=df.copy()
        df2["application_date"]=df2["application_date"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        cols=["first_name","last_name","email","country","application_date","yoe","seniority","technology","code_challenge_score","technical_interview","email_valid"]
        con.executemany(
            f"INSERT INTO {TABLE}({','.join(cols)}) VALUES ({','.join(['?']*len(cols))});",
            df2[cols].itertuples(index=False,name=None)
        )
        for ix in INDEXES: con.execute(ix)
    con.close()

def reports():
    con=sqlite3.connect(DB_PATH)
    tec=pd.read_sql_query(f"SELECT technology,COUNT(*) count FROM {TABLE} WHERE technology IS NOT NULL AND technology<>'' GROUP BY technology ORDER BY count DESC;",con)
    pais=pd.read_sql_query(f"SELECT country,COUNT(*) count FROM {TABLE} WHERE country IS NOT NULL AND country<>'' GROUP BY country ORDER BY count DESC;",con)
    exp=pd.read_sql_query(f"SELECT yoe,COUNT(*) count FROM {TABLE} GROUP BY yoe ORDER BY yoe ASC;",con)
    perf=pd.read_sql_query(f"SELECT code_challenge_score,technical_interview FROM {TABLE};",con)
    cohort=pd.read_sql_query(f"SELECT substr(application_date,1,7) ym,COUNT(*) count FROM {TABLE} WHERE application_date IS NOT NULL GROUP BY ym ORDER BY ym;",con)
    con.close()
    tec.to_csv("reporte_tecnologias.csv",index=False)
    pais.to_csv("reporte_paises.csv",index=False)
    exp.to_csv("reporte_experiencia.csv",index=False)
    def barh(df,x,y,title,out):
        if df.empty:return
        plt.figure(figsize=(8,5));plt.barh(df[y],df[x]);plt.title(title);plt.xlabel(x);plt.ylabel(y);plt.gca().invert_yaxis();plt.tight_layout();plt.savefig(out);plt.close()
    barh(tec.head(15),"count","technology","Top tecnologías","grafico_tecnologias.png")
    barh(pais.head(15),"count","country","Top países","grafico_paises.png")
    if not exp.empty:
        plt.figure(figsize=(8,5));plt.plot(exp["yoe"],exp["count"],marker="o");plt.title("Distribución YoE");plt.xlabel("YoE");plt.ylabel("Cantidad");plt.tight_layout();plt.savefig("grafico_experiencia.png");plt.close()
    if not perf.empty:
        plt.figure(figsize=(6,6));plt.scatter(perf["code_challenge_score"],perf["technical_interview"],alpha=0.4);plt.title("Code Challenge vs Technical Interview");plt.xlabel("Code Challenge");plt.ylabel("Technical Interview");plt.tight_layout();plt.savefig("grafico_ccs_vs_ti.png");plt.close()
    if not cohort.empty:
        plt.figure(figsize=(10,4));x=pd.to_datetime(cohort["ym"]+"-01");plt.plot(x,cohort["count"],marker="o");plt.title("Aplicaciones por mes");plt.xlabel("Mes");plt.ylabel("Cantidad");plt.tight_layout();plt.savefig("grafico_cohortes.png");plt.close()
    return ["reporte_tecnologias.csv","reporte_paises.csv","reporte_experiencia.csv","grafico_tecnologias.png","grafico_paises.png","grafico_experiencia.png","grafico_ccs_vs_ti.png","grafico_cohortes.png"]

def build_html(row):
    fn=(row.get("first_name") or "").title()
    tech=row.get("technology") or "your stack"
    seniority=row.get("seniority") or "your level"
    ccs=row.get("code_challenge_score");ti=row.get("technical_interview")
    ccs_txt="N/A" if pd.isna(ccs) else f"{float(ccs):.0f}"
    ti_txt="N/A" if pd.isna(ti) else f"{float(ti):.0f}"
    return f"""<html><body><p>Hi {fn},</p><p>Thanks for your application.</p>
<ul><li>Seniority: <b>{seniority}</b></li><li>Technology: <b>{tech}</b></li>
<li>Code Challenge: <b>{ccs_txt}</b></li><li>Technical Interview: <b>{ti_txt}</b></li></ul>
<p>We will contact you with next steps.</p><p>Best,<br/>Recruiting Team</p></body></html>"""

def send_emails(df,attachments):
    send_df=df[df["email_valid"]].copy()
    logs=[]
    if DRY_RUN:
        sample=send_df["email"].head(5).tolist()
        print("DRY_RUN activo. Primeros destinos:",sample)
        for em in sample: logs.append({"email":em,"status":"DRY_RUN","detail":"simulado"})
        pd.DataFrame(logs).to_csv("email_log.csv",index=False)
        return
    server=smtplib.SMTP(SMTP_HOST,SMTP_PORT);server.starttls();server.login(SENDER_EMAIL,SENDER_APP_PASSWORD)
    try:
        for _,row in send_df.iterrows():
            to_addr=SINGLE_SINK_EMAIL or row["email"]
            msg=MIMEMultipart();msg["From"]=SENDER_EMAIL;msg["To"]=to_addr;msg["Subject"]=EMAIL_SUBJECT
            msg.attach(MIMEText("HTML below.","plain"));msg.attach(MIMEText(build_html(row),"html"))
            for f in attachments:
                if not f or not os.path.exists(f):continue
                part=MIMEBase("application","octet-stream");part.set_payload(open(f,"rb").read());encoders.encode_base64(part)
                part.add_header("Content-Disposition",f'attachment; filename="{os.path.basename(f)}"');msg.attach(part)
            ok=False;err=""
            for _ in range(RETRIES+1):
                try: 
                    server.send_message(msg);ok=True;break
                except Exception as e: err=str(e)
            logs.append({"email":to_addr,"status":"SENT" if ok else "ERROR","detail":"" if ok else err})
            time.sleep(RATE_SLEEP)
    finally:
        server.quit()
        pd.DataFrame(logs).to_csv("email_log.csv",index=False)

def main():
    df=load_csv()
    print("Filas:",len(df),"| Emails válidos:",int(df["email_valid"].sum()))
    save_sqlite(df)
    attachments=reports()
    send_emails(df,attachments)
    print("OK. BD:",DB_PATH,"| Log de envíos: email_log.csv")

if __name__=="__main__":
    main()
