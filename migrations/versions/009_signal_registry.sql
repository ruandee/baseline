-- BL-30: preserve historical flat speech rows; new assessments store modality-keyed features.
ALTER TABLE assessments ADD COLUMN corroborated boolean NOT NULL DEFAULT false;
