# BareSand: bare sands of the north of Western Siberia

Supplementary materials to the article "Updated map of bare sands in the north of Western Siberia and its accuracy
assessment" (*Geodezia i Kartografia*, in Russian). The main documentation of the repository is in Russian; this file
summarizes it in English.

## Idea and objective

Open sandy surfaces are widespread in the permafrost zone of the northern West Siberian Plain and are a sensitive
indicator of tundra and northern taiga landscape dynamics. They form both by natural deflation on drained terraces and
interfluves and by technogenic destruction of the soil and vegetation cover during oil and gas field development,
construction of linear corridors and quarrying. Because natural revegetation in the Subarctic is slow, exposed quartz
sands remain sources of drifting sand for decades. Studying aeolian morphogenesis and monitoring the environmental
impact of field development therefore require separate inventories of natural and anthropogenic sands.

The first regional map of bare sands (Sizov and Lobzhanidze, 2022) was compiled from a multi-year Sentinel-2 mosaic
(2016-2020) by unsupervised classification with manual editing. The mosaic combined images of different years and water
stages, the manual cleaning removed oil field pads together with shoals, and the map accuracy was not assessed.

**Objective:** to refine the spatial distribution of bare sands in the north of Western Siberia, to assess the accuracy
of aeolian relief mapping and to analyse the structure of present-day anthropogenic disturbance. Alluvial and littoral
shoals are mapped as a separate class.

## Study area and data

The study area (1,068,411 km²) covers the Yamal-Nenets Autonomous Okrug, the northern part of the Khanty-Mansi
Autonomous Okrug (north of 61° N) and the western part of Krasnoyarsk Krai up to the Yenisei valley. The sand mask was
built on 128 Sentinel-2 MGRS tiles (906,325 km², 84.8% of the area) from 152 Sentinel-2 L2A scenes acquired in
July-September 2020-2025 (one scene per tile; mosaics of two or three scenes for 22 tiles). Auxiliary data: JRC Global
Surface Water, MERIT Hydro, ArcticDEM v4.1, ALOS AW3D30, Global Forest Change, MODIS MCD64A1, Landsat 5 (1984-1995),
OpenStreetMap, land parcels of the Unified State Register of Real Estate (EGRN), AlphaEarth Foundations embeddings and
Esri World Imagery. Processing was done in Google Earth Engine and Python in the Lambert azimuthal equal-area
projection (EPSG:3576).

## Methods

1. **Sand mask.** Each tile was classified separately from its own summer scene with the author's training points.
   Clouds and shadows were removed with the scene classification layer without masking bare soil; water and dense
   vegetation were excluded with MNDWI and NDVI thresholds. A Random Forest classifier on ten Sentinel-2 bands (including
   red edge and SWIR) and spectral indices separated sand from dry lichen barrens (mean F1 = 0.93 on six calibration
   scenes, S1, S2). The mask was vectorized with a minimum mapping unit of 900 m².
2. **Genesis attribution.** A hierarchical rule cascade (S3) split the mask polygons into aeolian sands (blowouts, dune
   fields, deflation hollows), anthropogenic sands (pads, road fills, quarries, corridors) and alluvial-littoral shoals.
   Shoals were identified by water recurrence and proximity to water bodies and the sea; anthropogenic sands by indirect
   evidence (OpenStreetMap objects, EGRN parcels, absence of bare surface in 2000); aeolian sands by inter-annual
   stability, absence of flooding and clustering. Undefined and channel-side aeolian polygons were refined with the
   height above the local base level from ArcticDEM, the median polygon elevation minus the 5th percentile of
   elevations within a 600 m outer buffer (S4). The remaining undefined polygons were labelled blindly by the author,
   and the labels were transferred to similar polygons by an ensemble of models using object features and AlphaEarth
   embeddings (S5).
3. **Accuracy assessment.** Attribution accuracy within the mask was estimated for the map version before point
   corrections (8,061 km²) from a stratified sample of 276 polygons (strata: map class and polygon area) with blind
   reference labels by the author. Error matrix cell areas, accuracies and confidence intervals (within-stratum
   bootstrap) follow the area-based estimators of Olofsson et al. (2014) and Stehman (2014) (S6).
4. **Point corrections.** After the accuracy assessment, aeolian polygons within 20 m of roads and anthropogenic sands
   were re-examined from imagery by a multimodal model and by the author; reclassifications were checked with a
   control sample of the final layer (S9, S10).
5. **Anthropogenic sands and land allocation.** Anthropogenic sands were overlaid with an operational layer of land
   allocations: EGRN parcels with a compatible land category and permitted use, and settlement territory. With a 10 m
   tolerance, three groups were distinguished: within allocations, parts beyond allocations, and objects without an
   allocation; the share of surfaces already bare in 2000 was computed for each group (S11).

## Results

| Class | Polygons | Area, km² | Share of mask area, % |
|---|---|---|---|
| aeolian sands | 347,885 | 2,729.7 | 33.5 |
| shoals (river 3,053.7; sea 315.8; lake 136.6 km²) | 132,994 | 3,506.0 | 43.0 |
| anthropogenic sands | 82,729 | 1,876.2 | 23.0 |
| undefined | 11,446 | 43.8 | 0.5 |
| total | 575,054 | 8,155.7 | 100 |

Accuracy of aeolian sands (map version before point corrections, 95% confidence intervals): user's accuracy 94.9%
(86.2-99.5%), producer's accuracy 86.0% (73.6-98.9%), F1 0.90 (0.82-0.99), reference-based area 3,024.0 km²
(2,508.6-3,540.6). Overall accuracy of the three main classes is 91.6% (84.7-98.0%). The main confusion is between
aeolian covers of low terraces and shoals, which are separated by the height above the local base level (median 6.0 m
for aeolian sands and 0.5 m for shoals; area under the ROC curve 0.94).

Aeolian sands cluster north of 68° N (70% of the class; 61.3% in the Yamalsky District) and reproduce the district
pattern of the 2022 map despite a 41% methodological increase in area. Anthropogenic sands concentrate in the northern
taiga of the Nadym-Pur-Taz and Middle Ob regions (85.2%) and within oil and gas fields (68.3%). According to EGRN,
58.7% of their area lies within land allocations; objects without an allocation (349.3 km²) are mostly post-2000,
whereas parts beyond allocations (243.0 km²) are dominated by surfaces already bare in 2000.

## Repository contents

| Folder or file | Contents |
|---|---|
| [supplement/](supplement/README.md) | supplementary sections S1-S12 cited in the article (in Russian) |
| [docs/INTERPRETATION.md](docs/INTERPRETATION.md) | interpretation method for bare sands and their genesis |
| [docs/METHODS.md](docs/METHODS.md) | processing algorithms, rules and thresholds |
| [docs/DATA.md](docs/DATA.md) | final layers, classes, fields and source data |
| [src/](src/README.md) | processing code: Google Earth Engine (JavaScript) and Python scripts |
| [gee_app/](gee_app/README.md) | interactive map in Google Earth Engine |

## Interactive map

<https://nodal-thunder-481307-u1.projects.earthengine.app/view/baresand>

The map shows the genesis layer, sand density by class in 10, 5 and 2 km cells (switching with zoom), anthropogenic
sands against a generalized mask of land allocations, the source Sentinel-2 scenes and the sand mask, reference layers
(OpenStreetMap infrastructure, ArcticDEM relief, JRC surface water, Hansen forest cover) and dynamic statistics by
district. Polygons of the visible area can be downloaded as GeoJSON, KML or CSV.

## Citation

Sizov O.S. BareSand: bare sands of the north of Western Siberia. Supplementary materials to the article "Updated map of
bare sands in the north of Western Siberia and its accuracy assessment". 2026.
URL: https://github.com/SizovOleg/baresand-zapsib. Machine-readable record: [CITATION.cff](CITATION.cff).

## Licenses

Code: MIT ([LICENSE](LICENSE)). Documentation and data: CC BY 4.0. Parts derived from OpenStreetMap: ODbL 1.0
([LICENSE-DATA.md](LICENSE-DATA.md)). EGRN data are used in generalized form.

## References

- Sizov O.S., Lobzhanidze N.E. Spatial distribution of natural and anthropogenic aeolian relief in the north of Western
  Siberia. *Geodezia i Kartografia*, 2022, 83 (8), pp. 22-32. DOI: 10.22389/0016-7126-2022-986-8-22-32.
- Olofsson P., Foody G.M., Herold M., et al. Good practices for estimating area and assessing accuracy of land change.
  *Remote Sensing of Environment*, 2014, 148, pp. 42-57. DOI: 10.1016/j.rse.2014.02.015.
- Stehman S.V. Estimating area and map accuracy for stratified random sampling when the strata are different from the
  map classes. *International Journal of Remote Sensing*, 2014, 35 (13), pp. 4923-4939.
  DOI: 10.1080/01431161.2014.930207.
