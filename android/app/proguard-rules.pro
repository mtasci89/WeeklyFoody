# Uygulamanın kendi kodu olduğu gibi kalır: JSON modelleri (kotlinx.serialization) ve
# Compose ekranları ad değiştirmeden çalışsın, hata kayıtları okunabilir olsun.
-keep class com.foody.** { *; }
-keepattributes *Annotation*, InnerClasses, Signature, SourceFile, LineNumberTable

# EncryptedSharedPreferences (Tink) derleme zamanı açıklamaları; çalışma anında gerekmez.
-dontwarn com.google.errorprone.annotations.**
-dontwarn javax.annotation.**

# Tink anahtar kayıtlarını yansıma (reflection) ile okur; alanlar silinirse şifreli ayarlar açılamaz.
-keepclassmembers class * extends com.google.crypto.tink.shaded.protobuf.GeneratedMessageLite { <fields>; }
