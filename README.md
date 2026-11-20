# GC и управление памятью — домашнее задание 2

**[Отчёт с результатами и иллюстрациями](report/report.md)** · [Исходный код](src/MemoryLab.java) · [Измерения](results/)

Два консольных JVM-процесса с одинаковой нагрузкой показывают утечку через статическую коллекцию и её исправление ограничением количества элементов. Выполнены реальные замеры jstat, анализ GCViewer, снятие heap dump через jcmd и анализ Eclipse MAT. Spring, база данных и сеть для самого примера не нужны.

## Повторить опыт

Нужны **JDK 17+** (включая javac, jcmd, jstat) и **Python 3.9+**. Проверено на Amazon Corretto 17.0.19, macOS ARM64. Флаги и формат GC относятся к HotSpot; время до OOM на другой машине может отличаться.

Из папки проекта:

```sh
python3 scripts/run_experiment.py --java-home /absolute/path/to/jdk --output results-new
```

В Windows передайте путь к каталогу JDK; для текущего скрипта используйте macOS/Linux, где утилиты JDK называются без `.exe`. Java-код переносим.

Скрипт компилирует программу, запускает `leak` и `bounded` в отдельных JVM с heap по 128 МиБ, включает GC-логи и jstat. Примерно на 70-й секунде он снимает два дампа, гистограммы классов и состояние heap. Опыт занимает около двух минут. Ожидаемый результат: `leak` завершается с OOM и кодом 3, `bounded` — нормально с кодом 0. Скрипт проверяет эти результаты и наличие обоих дампов. Для повторного запуска выбирайте новый каталог: сохранённые результаты не перезаписываются.

Нагрузка: восемь массивов по 64 КиБ каждые 400 мс, примерно 1,25 МиБ/с. В режиме `leak` все объекты остаются в статическом `ArrayDeque`; в `bounded` сохраняются последние 64 объекта. Поток `payload-allocator` создаёт объекты; daemon-поток `heap-sampler` раз в секунду измеряет heap и через Stream API суммирует размеры удерживаемых массивов. Чтение и изменение коллекции защищены одной блокировкой.

Файлы `heap.hprof` остаются локально и исключены из Git. В репозитории есть вывод jcmd, SHA-256 дампов, гистограммы и полные отчёты MAT в ZIP. Дампы можно получить повторным запуском.

## Ручной запуск и диагностика

Для этих команд `java`, `javac`, `jcmd`, `jstat` должны относиться к одному JDK и быть доступны в PATH:

```sh
mkdir -p build manual-run
javac --release 17 -d build src/MemoryLab.java
cd manual-run
java -Xms128m -Xmx128m -XX:+UseG1GC -XX:+ExitOnOutOfMemoryError \
  '-Xlog:gc*=info:file=gc.log:uptime,level,tags:filecount=0' \
  -cp ../build MemoryLab leak 120 > heap.csv 2> application.txt
```

В другом терминале, пока процесс работает:

```sh
jcmd -l
jstat -gc -t PID 1000 > jstat.txt
jcmd PID GC.heap_dump heap.hprof
jcmd PID GC.class_histogram > histogram.txt
jcmd PID GC.heap_info > heap-info.txt
```

Замените `PID` на идентификатор **именно MemoryLab**. Относительный путь дампа разрешается в рабочей папке исследуемой JVM. `jcmd` должен запускаться тем же пользователем. `GC.heap_dump` и `GC.class_histogram` без `-all` инициируют полную сборку: она учитывается отдельно при интерпретации результата. При ручном запуске остановите jstat после окончания JVM. Для контрольного опыта используйте новую папку и замените `leak` на `bounded`.

`ExitOnOutOfMemoryError` предназначен здесь для воспроизводимого завершения учебного процесса при OOM. Он не устраняет утечку. JVM добавляет строку `Terminating due to ...` в конец stdout; анализатор пропускает её при чтении `heap.csv`.

## GCViewer

Скачайте [GCViewer 1.37 с официальной страницы проекта](https://github.com/chewiebug/GCViewer/wiki/Changelog) в `.tools/gcviewer-1.37.jar`. Проверенная SHA-256: `325a5f1a8f67588b6845c71eceb70c8b74c45930fd553ba2fc7b3b4118608e13`.

```sh
java -Duser.language=en -Duser.country=US -Djava.awt.headless=true \
  -jar .tools/gcviewer-1.37.jar \
  results/leak/gc.log results/leak/gcviewer.csv \
  report/images/gcviewer-leak.png -t SUMMARY
```

Повторите для `bounded`. Для собственного опыта замените `results` на выбранный каталог. Запуск без аргументов файлов открывает GUI GCViewer, где можно выбрать `gc.log`. Графики в отчёте экспортированы самим GCViewer через CLI.

## Eclipse MAT

Использован [Eclipse MAT 1.17.0](https://eclipse.dev/mat/download/) с **JDK 25**; для самого MAT 1.17 нужен JDK 21+, хотя исследуемое приложение работает на JDK 17. Анализ выполнялся в официальном [batch mode](https://help.eclipse.org/latest/topic/org.eclipse.mat.ui.help/tasks/batch.html).

На macOS, если архив распакован в `.tools/mat`, команда для использованной версии:

```sh
/path/to/jdk21-or-newer/bin/java -XstartOnFirstThread -Djava.awt.headless=true -Xmx512m \
  -jar .tools/mat/MemoryAnalyzer.app/Contents/Eclipse/plugins/org.eclipse.equinox.launcher_1.7.100.v20251111-0406.jar \
  -consoleLog -nosplash -application org.eclipse.mat.api.parse \
  results/leak/heap.hprof org.eclipse.mat.api:suspects
```

Повторите для `bounded`. `-XstartOnFirstThread` нужен macOS-версии для генерации диаграмм; на Linux его не добавляют. В других дистрибутивах MAT можно использовать штатный `ParseHeapDump.sh` / `ParseHeapDump.bat`, указав подходящий JDK.

MAT создаёт `heap_Leak_Suspects.zip` рядом с дампом. Распакуйте ZIP и откройте `index.html`. Переход **Problem Suspect → Details → Shortest Paths To the Accumulation Point** показывает поле `RETAINED`. Ссылки вида `mat://` выполняют интерактивные запросы только в MAT; статические таблицы и обычные ссылки HTML работают в браузере.

Для просмотра готовых результатов без установки MAT скачайте и распакуйте [отчёт с утечкой](results/leak/heap_Leak_Suspects.zip) и [контрольный отчёт](results/bounded/heap_Leak_Suspects.zip).

## Проверка чисел и построение графика

`scripts/analyze.py` читает сохранённые `results`, сверяет число и сумму GC-пауз с экспортом GCViewer, проверяет лимит 64 объектов и время заполнения heap. Для графика нужен `matplotlib`:

```sh
python3 -m venv .tools/plot-env
.tools/plot-env/bin/pip install matplotlib==3.9.4
.tools/plot-env/bin/python scripts/analyze.py
```

Файл `results/analysis.json` содержит расчёты, исходные значения находятся в `gc.log`, `jstat.txt`, `heap.csv`. Ни график, ни отчёт не заменяют сырые измерения. `jstat` в этом опыте использовал десятичную запятую; анализатор учитывает её. Повторяющиеся строки с последним timestamp после остановки JVM не являются новыми замерами.

В личный кабинет курса нужно самостоятельно отправить ссылку на [отчёт](report/report.md).
