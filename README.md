# db_editor

Çok basit iki masaüstü video editörü uygulaması içerir: biri MP4 üzerine
mikrofonla ses dublajı yapar (`app.py`), diğeri MP4'ten istediğiniz
bölüm(ler)i kesip çıkarır ve kalanı yeni bir dosya olarak dışa aktarır
(`cutter_app.py`).

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

Bu uygulama, videoyu "yalnızca seçilen aralığı tut" mantığıyla değil,
**"işaretlenen bölüm(ler)i videodan çıkar, geri kalanı birleştir"**
mantığıyla çalışır. Yani örneğin videonun 10.-15. saniyelerini
işaretleyip çıkarırsanız, sonuçta 0-10 ile 15-son arası birleştirilmiş
tek bir video elde edersiniz (10-15 arası tamamen silinmiş olur).
Birden fazla bölüm işaretleyip aynı anda çıkarabilirsiniz.

### Çalıştırma

```bash
python cutter_app.py
```

### Kullanım

1. **MP4 Aç...** ile bir video dosyası seçin.
2. Zaman çubuğunu sürükleyerek videoda gezinin; önizleme karesi anlık
   güncellenir.
3. Çıkarmak istediğiniz bölümün başlangıç/bitişini **Buradan İşaretle**
   ile (ya da saniye cinsinden doğrudan kutulara yazıp **Git** ile o
   noktaya atlayarak) belirleyin. **Seçimi Önizle** ile bu aralığı
   oynatarak kontrol edebilirsiniz.
4. **➕ Bu Aralığı Listeye Ekle** ile işaretlediğiniz bölümü "çıkarılacak
   bölümler" listesine ekleyin. İsterseniz birden fazla bölüm ekleyin;
   liste otomatik olarak çakışan/bitişik aralıkları birleştirir ve kalan
   video uzunluğunu gösterir. Yanlış eklenen bir satırı **Seçili Satırı
   Sil** ile kaldırabilir, **Listeyi Temizle** ile hepsini silebilirsiniz.
5. **✂ Bölümleri Çıkar ve Dışa Aktar** ile listedeki bölümler videodan
   çıkarılmış, kalanı birleştirilmiş yeni bir MP4 dosyası kaydedin.

### Notlar

- Varsayılan kesim modu hızlıdır (ses/görüntü yeniden kodlanmaz, `stream
  copy`), ancak kesim noktaları en yakın keyframe'e yuvarlanabilir.
- **"Kare hassasiyetiyle kes"** kutusunu işaretlerseniz her parça yeniden
  kodlanır (daha yavaştır) ama kesim noktaları tam olarak belirttiğiniz
  saniyeden başlar/biter.
- Birden fazla bölüm çıkarıldığında, kalan parçalar `ffmpeg`'in `concat`
  demuxer'ı ile birleştirilir; parametre uyuşmazlığı olursa uygulama
  otomatik olarak yeniden kodlayarak birleştirmeyi dener.
- Kesme işlemi için de `imageio-ffmpeg` paketiyle gelen ffmpeg binary'si
  kullanılır.

### Kare Dondur (ekranda durup konuşma kaydetmek için)

Aynı pencerede, videonun belirli bir anındaki kareyi bir süreliğine
dondurup videoyu o kadar uzatabileceğiniz bir bölüm de bulunur. Bunu,
örneğin bir sunumda belirli bir ekranda durup üzerine sesli anlatım
kaydetmek istediğinizde kullanabilirsiniz:

1. **Dondurulacak an (sn)** kutusuna zaman çubuğundaki konumdan
   **Buradan İşaretle** ile ya da doğrudan saniye yazarak bir nokta seçin.
2. **Dondurma süresi (sn)** kutusuna karenin ne kadar süre sabit kalacağını
   yazın.
3. **🧊 Kareyi Dondur ve Dışa Aktar** ile yeni bir MP4 oluşturun: seçilen
   kare belirttiğiniz süre boyunca ekranda sabit kalır, video toplam
   uzunluğu bu süre kadar artar.
4. Dondurulan bölümün sesi sessizdir; isterseniz çıkan dosyayı `app.py`
   ile açıp o bölüme mikrofonunuzdan konuşma kaydedebilirsiniz.

Bu işlem videoyu üç parçaya (dondurma anına kadar, dondurulmuş kare,
dondurma anından sona kadar) ayırıp yeniden kodlayarak birleştirir, bu
yüzden kesmeye göre biraz daha uzun sürebilir.
