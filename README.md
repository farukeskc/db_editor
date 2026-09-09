# db_editor

Çok basit bir masaüstü uygulama: bir MP4 dosyasını açar, oynatırken mikrofondan
ses kaydeder ve kaydedilen sesi videoyla birleştirip (orijinal sesin yerine)
yeni bir MP4 dosyası olarak dışa aktarır.

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Çalıştırma

```bash
python app.py
```

## Kullanım

1. **MP4 Aç...** ile bir video dosyası seçin.
2. İsterseniz **Önizle** ile videoyu (sessiz) izleyin.
3. **Kayda Başla** butonuna basın: video oynatılırken mikrofonunuzdan ses
   kaydedilir. Video bitince kayıt otomatik durur (veya butona tekrar basıp
   erken durdurabilirsiniz).
4. **Kaydet** ile videoyu, kaydettiğiniz sesle birleştirip yeni bir MP4
   dosyası olarak dışa aktarın.

## Notlar

- Video/ses birleştirme için `imageio-ffmpeg` paketiyle gelen ffmpeg
  binary'si kullanılır; ayrıca sisteme ffmpeg kurmanıza gerek yoktur.
- Orijinal video görüntüsü aynen korunur (yeniden kodlanmaz), sadece ses
  parçası mikrofon kaydınızla değiştirilir.
