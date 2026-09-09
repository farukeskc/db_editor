# db_editor

Çok basit iki masaüstü video editörü uygulaması içerir: biri MP4 üzerine
mikrofonla ses dublajı yapar (`app.py`), diğeri MP4 videolarını kesip
(trim) yeni bir dosya olarak dışa aktarır (`cutter_app.py`).

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Ses Dublaj Editörü (`app.py`)

### Çalıştırma

```bash
python app.py
```

### Kullanım

1. **MP4 Aç...** ile bir video dosyası seçin.
2. İsterseniz **Önizle** ile videoyu (sessiz) izleyin.
3. **Kayda Başla** butonuna basın: video oynatılırken mikrofonunuzdan ses
   kaydedilir. Video bitince kayıt otomatik durur (veya butona tekrar basıp
   erken durdurabilirsiniz).
4. **Kaydet** ile videoyu, kaydettiğiniz sesle birleştirip yeni bir MP4
   dosyası olarak dışa aktarın.

### Notlar

- Video/ses birleştirme için `imageio-ffmpeg` paketiyle gelen ffmpeg
  binary'si kullanılır; ayrıca sisteme ffmpeg kurmanıza gerek yoktur.
- Orijinal video görüntüsü aynen korunur (yeniden kodlanmaz), sadece ses
  parçası mikrofon kaydınızla değiştirilir.

## Kesme (Cut) Editörü (`cutter_app.py`)

### Çalıştırma

```bash
python cutter_app.py
```

### Kullanım

1. **MP4 Aç...** ile bir video dosyası seçin.
2. Zaman çubuğunu sürükleyerek videoda gezinin; önizleme karesi anlık
   güncellenir.
3. İstediğiniz noktada **Buradan İşaretle** ile başlangıç/bitiş zamanlarını
   belirleyin (ya da saniye cinsinden doğrudan kutulara yazıp **Git** ile
   o noktaya atlayın).
4. **Seçimi Önizle** ile seçtiğiniz aralığı oynatarak kontrol edin.
5. **✂ Kes ve Dışa Aktar** ile seçili aralığı yeni bir MP4 dosyası olarak
   kaydedin.

### Notlar

- Varsayılan kesim modu hızlıdır (ses/görüntü yeniden kodlanmaz, `stream
  copy`), ancak başlangıç noktası en yakın keyframe'e yuvarlanabilir.
- **"Kare hassasiyetiyle kes"** kutusunu işaretlerseniz video yeniden
  kodlanır (daha yavaştır) ve kesim tam olarak belirttiğiniz saniyeden
  başlar.
- Kesme işlemi için de `imageio-ffmpeg` paketiyle gelen ffmpeg binary'si
  kullanılır.
