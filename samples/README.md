# Sample DICOM files

Five de-identified CT slices so the pipeline can be run straight after cloning:

```bash
cp samples/*.dcm data/          # Windows PowerShell: Copy-Item samples\*.dcm data\
docker compose up --build
```

| | |
|---|---|
| Collection | LIDC-IDRI (Lung Image Database Consortium image collection) |
| Subject | `LIDC-IDRI-0580`, one chest CT series (GE Medical Systems) |
| Files | `instance-0155.dcm` to `instance-0159.dcm`, about 2.6 MB in total |
| De-identification | Done by the data publisher: patient name, birth date and referring physician are empty and `PatientIdentityRemoved` is `YES` |
| Obtained from | [Saga IT DICOM samples](https://saga-it.com/dicom/samples), which redistributes CC BY studies from the NCI Imaging Data Commons |
| Original source | [The Cancer Imaging Archive (TCIA)](https://www.cancerimagingarchive.net/collection/lidc-idri/) |
| License | [Creative Commons Attribution 3.0 (CC BY 3.0)](https://creativecommons.org/licenses/by/3.0/) |

## Data citation

Armato III, S. G., McLennan, G., Bidaut, L., McNitt-Gray, M. F., Meyer, C. R., Reeves, A. P., Zhao, B., Aberle, D. R., Henschke, C. I., Hoffman, E. A., Kazerooni, E. A., MacMahon, H., Van Beek, E. J. R., Yankelevitz, D., Biancardi, A. M., Bland, P. H., Brown, M. S., Engelmann, R. M., Laderach, G. E., Max, D., Pais, R. C., Qing, D. P. Y., Roberts, R. Y., Smith, A. R., Starkey, A., Batra, P., Caligiuri, P., Farooqi, A., Gladish, G. W., Jude, C. M., Munden, R. F., Petkovska, I., Quint, L. E., Schwartz, L. H., Sundaram, B., Dodd, L. E., Fenimore, C., Gur, D., Petrick, N., Freymann, J., Kirby, J., Hughes, B., Casteele, A. V., Gupte, S., Sallam, M., Heath, M. D., Kuhn, M. H., Dharaiya, E., Burns, R., Fryd, D. S., Salganicoff, M., Anand, V., Shreter, U., Vastagh, S., Croft, B. Y., Clarke, L. P. (2015). *Data From LIDC-IDRI* [Data set]. The Cancer Imaging Archive. https://doi.org/10.7937/K9/TCIA.2015.LO9QL9SX

## Acknowledgement

The authors acknowledge the National Cancer Institute and the Foundation for the National Institutes of Health, and their critical role in the creation of the free publicly available LIDC/IDRI Database used in this study.

The files are unmodified. No endorsement by the data creators is implied.
