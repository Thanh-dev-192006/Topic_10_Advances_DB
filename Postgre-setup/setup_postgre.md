# Hướng Dẫn Tạo PostgreSQL Database — Recruitment Matcher

## Tổng quan: Bạn cần làm gì?

```
Bước 1: Tạo database trống trong pgAdmin
Bước 2: Cài thư viện Python
Bước 3: Sửa DB_CONFIG trong script
Bước 4: Chạy script → tự động tạo bảng + insert 1000 JD + 1000 CV
Bước 5: Kiểm tra kết quả trong pgAdmin
```

---

## Bước 1: Tạo Database Trong pgAdmin

Mở pgAdmin → làm theo các bước sau:

**1.1** Click chuột phải vào **Databases** (trong cây bên trái) → chọn **Create → Database...**

**1.2** Điền thông tin:
```
Database : recruitment_db
Owner    : postgres          ← hoặc user của bạn
Encoding : UTF8              ← quan trọng, để đọc được tiếng Anh đúng
```

**1.3** Click **Save** → database `recruitment_db` xuất hiện trong cây.

> Không cần tạo bảng thủ công trong pgAdmin — script Python sẽ tự tạo.

---

## Bước 2: Tìm Password PostgreSQL Của Bạn

Vì bạn dùng pgAdmin và không thấy hỏi mật khẩu, có 2 khả năng:

**Khả năng A — pgAdmin đã lưu mật khẩu sẵn:**
- Trong pgAdmin → click vào server (thường là "PostgreSQL 16") → Properties
- Xem tab **Connection** → trường **Password**
- Copy mật khẩu đó điền vào script

**Khả năng B — PostgreSQL đang dùng trust auth (không cần mật khẩu):**
- Để `"password": ""` trong DB_CONFIG → script vẫn kết nối được
- Nếu chạy script báo lỗi authentication → thử khả năng A

---

## Bước 3: Cài Thư Viện Python

Mở terminal (Command Prompt / PowerShell / Terminal) và chạy:

```bash
pip install psycopg2-binary datasets
```

Kiểm tra cài thành công:
```bash
python -c "import psycopg2; import datasets; print('OK')"
```

---

## Bước 4: Sửa DB_CONFIG Trong Script

Mở file `setup_postgres_db.py`, tìm phần này ở đầu file và sửa:

```python
DB_CONFIG = {
    "host":     "localhost",        # Giữ nguyên nếu PostgreSQL chạy trên máy này
    "port":     5432,               # Port mặc định, thường không đổi
    "dbname":   "recruitment_db",   # Tên database vừa tạo ở Bước 1
    "user":     "postgres",         # Username PostgreSQL của bạn
    "password": "",                 # Để "" nếu không hỏi mật khẩu
                                    # Điền mật khẩu nếu có
}
```

---

## Bước 5: Chạy Script

```bash
python setup_postgres_db.py
```

Script sẽ chạy qua 4 giai đoạn và in ra:

```
=======================================================
  Recruitment DB Setup — PostgreSQL
  Target: 1000 JDs + 1000 CVs
=======================================================

[1/4] Đang load dataset từ HuggingFace...       ← download từ internet (~vài phút)
   Raw JDs: 1000 | Raw CVs: 1000
   JD columns: ['Position', 'Long Description', ...]
   CV columns: ['Position', 'CV', 'Highlights', ...]

[2/4] Đang clean data...
   JD: giữ 990, bỏ 10 (rỗng/ngắn)
   CV: giữ 995, bỏ 5 (rỗng/ngắn)

   Connecting to PostgreSQL: localhost:5432/recruitment_db...
   ✓ Kết nối thành công

[3/4] Đang tạo schema...
   Dropped tables cũ (nếu có)
   ✓ Tạo bảng job_descriptions
   ✓ Tạo bảng cvs
   ✓ Tạo 6 GIN indexes

[4/4] Đang insert data...
   ✓ Inserted 990 job descriptions
   ✓ Inserted 995 candidate CVs

=======================================================
  VERIFY — Kiểm tra data trong PostgreSQL
=======================================================
  Tổng job_descriptions : 990
  Tổng cvs              : 995
  ...
  ✅ Database sẵn sàng sử dụng!
```

---

## Bước 6: Kiểm Tra Kết Quả Trong pgAdmin

Sau khi script chạy xong, vào pgAdmin kiểm tra:

**6.1** Mở cây: `recruitment_db → Schemas → public → Tables`
→ Phải thấy 2 bảng: `job_descriptions` và `cvs`

**6.2** Click chuột phải vào bảng `cvs` → **View/Edit Data → First 100 Rows**
→ Phải thấy data hiện ra

**6.3** Mở Query Tool (biểu tượng SQL) và chạy thử:

```sql
-- Đếm tổng bản ghi
SELECT COUNT(*) FROM job_descriptions;
SELECT COUNT(*) FROM cvs;

-- Xem cấu trúc bảng
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'cvs';

-- Thử tìm kiếm LIKE
SELECT id, position, keyword
FROM cvs
WHERE cv_text ILIKE '%python%'
LIMIT 5;
```

---

## Cấu Trúc 2 Bảng Được Tạo

### Bảng `job_descriptions`
| Cột | Kiểu | Ý nghĩa |
|-----|------|---------|
| id | SERIAL PRIMARY KEY | Tự tăng |
| position | VARCHAR(300) | Tên vị trí tuyển dụng |
| description | TEXT | Mô tả công việc chi tiết |
| company | VARCHAR(200) | Tên công ty |
| keyword | VARCHAR(300) | Từ khoá kỹ năng chính |
| exp_years | VARCHAR(50) | Số năm kinh nghiệm yêu cầu |
| created_at | TIMESTAMP | Thời gian insert |

### Bảng `cvs`
| Cột | Kiểu | Ý nghĩa |
|-----|------|---------|
| id | SERIAL PRIMARY KEY | Tự tăng |
| position | VARCHAR(300) | Vị trí ứng viên ứng tuyển |
| cv_text | TEXT | Nội dung CV đầy đủ |
| highlights | TEXT | Điểm nổi bật |
| keyword | VARCHAR(300) | Kỹ năng chính |
| exp_years | VARCHAR(50) | Số năm kinh nghiệm |
| looking_for | TEXT | Ứng viên đang tìm kiếm gì |
| created_at | TIMESTAMP | Thời gian insert |

---

## Xử Lý Lỗi Thường Gặp

### `connection refused` / `could not connect`
```
Nguyên nhân : PostgreSQL chưa chạy
Kiểm tra    : Mở pgAdmin — nếu pgAdmin kết nối được thì PostgreSQL đang chạy
              Nếu không → tìm "PostgreSQL" trong Services (Windows) hoặc
              sudo systemctl start postgresql (Linux)
```

### `password authentication failed`
```
Nguyên nhân : Sai mật khẩu hoặc để "" nhưng server yêu cầu mật khẩu
Cách sửa    : Xem mật khẩu trong pgAdmin → server Properties → Connection
              Điền vào "password" trong DB_CONFIG
```

### `database "recruitment_db" does not exist`
```
Nguyên nhân : Chưa tạo database ở Bước 1
Cách sửa    : Quay lại Bước 1, tạo database trong pgAdmin
```

### HuggingFace download chậm hoặc lỗi
```
Nguyên nhân : Mạng yếu hoặc HuggingFace bị timeout
Cách sửa    : Chạy lại script — datasets library tự cache, không download lại từ đầu
              Lần đầu có thể mất 3-5 phút tuỳ tốc độ mạng
```