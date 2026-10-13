/**
 * BareSand — Утилиты оценки точности классификации
 *
 * Confusion matrix, OA, Kappa, F1 по классу песка.
 * Используется всеми методами классификации (10–14).
 *
 * Использование:
 *   var acc = require('users/USERNAME/baresand:gee_scripts/utils/accuracy');
 *   var metrics = acc.computeAccuracy(classified, testData, 10);
 *   acc.printAccuracyReport(metrics);
 */

/**
 * Вычислить confusion matrix и метрики точности.
 * @param {ee.Image} classified — классифицированное изображение (band 'classification')
 * @param {ee.FeatureCollection} validation — валидационная выборка с полем 'class'
 * @param {Number} scale — пространственное разрешение (10 для S2)
 * @return {Object} {matrix, oa, kappa, f1_sand, producers_sand, users_sand, perClass}
 */
function computeAccuracy(classified, validation, scale) {
  // Сэмплирование: значения классификации в точках валидации
  var validated = classified.select('classification').sampleRegions({
    collection: validation,
    properties: ['class'],
    scale: scale,
    geometries: false
  });

  // Confusion matrix: строки — reference (class), столбцы — mapped (classification)
  var errorMatrix = validated.errorMatrix('class', 'classification');

  // Overall Accuracy
  var oa = errorMatrix.accuracy();

  // Cohen's Kappa
  var kappa = errorMatrix.kappa();

  // Per-class метрики из confusion matrix
  var producersAcc = errorMatrix.producersAccuracy();  // по строкам
  var consumersAcc = errorMatrix.consumersAccuracy();  // по столбцам (User's)

  // F1 для класса 0 (bare_sand) — главная метрика
  // F1 = 2 * (Precision * Recall) / (Precision + Recall)
  // Precision = User's accuracy (consumers), Recall = Producer's accuracy
  var sandClass = 0;
  var producers_sand = ee.Number(producersAcc.get([sandClass, 0]));
  var users_sand = ee.Number(consumersAcc.get([sandClass, 0]));
  var f1_sand = ee.Number(2)
    .multiply(producers_sand).multiply(users_sand)
    .divide(producers_sand.add(users_sand));

  return {
    matrix: errorMatrix,
    oa: oa,
    kappa: kappa,
    f1_sand: f1_sand,
    producers_sand: producers_sand,
    users_sand: users_sand,
    producersAll: producersAcc,
    consumersAll: consumersAcc
  };
}

/**
 * Напечатать отчёт по точности в консоль GEE.
 * @param {Object} metrics — результат computeAccuracy
 * @param {Array} classNames — массив имён классов (опционально)
 */
function printAccuracyReport(metrics, classNames) {
  classNames = classNames || [
    'bare_sand', 'lichen_barren', 'gravel', 'bare_peat',
    'anthropogenic', 'vegetation', 'water', 'snow_ice'
  ];

  print('═══════════════════════════════════════');
  print('ОТЧЁТ ПО ТОЧНОСТИ КЛАССИФИКАЦИИ');
  print('═══════════════════════════════════════');
  print('');
  print('Confusion Matrix:');
  print(metrics.matrix);
  print('');
  print('Overall Accuracy (OA):', metrics.oa);
  print('Cohen\'s Kappa:', metrics.kappa);
  print('');
  print('── Класс bare_sand (целевой) ──');
  print('F1 (sand):', metrics.f1_sand);
  print('Producer\'s Accuracy (полнота):', metrics.producers_sand);
  print('User\'s Accuracy (точность):', metrics.users_sand);
  print('');
  print('── Per-class Producer\'s Accuracy ──');
  print(metrics.producersAll);
  print('');
  print('── Per-class User\'s Accuracy ──');
  print(metrics.consumersAll);

  // Порог качества (DNA §4.1)
  print('');
  print('── Порог F1(sand) >= 0.80 ──');
  // Серверная проверка
  var passed = ee.Algorithms.If(
    ee.Number(metrics.f1_sand).gte(0.80),
    '✓ ПРОЙДЕН',
    '✗ НЕ ПРОЙДЕН (ниже целевого порога)'
  );
  print('Статус:', passed);
}

// Экспорт
exports.computeAccuracy = computeAccuracy;
exports.printAccuracyReport = printAccuracyReport;
