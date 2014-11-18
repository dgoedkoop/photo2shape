# -*- coding: utf-8 -*-

"""
***************************************************************************
    importthread.py
    ---------------------
    Date                 : July 2013
    Copyright            : (C) 2013-2014 by Alexander Bruy
    Email                : alexander dot bruy at gmail dot com
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

__author__ = 'Alexander Bruy'
__date__ = 'July 2013'
__copyright__ = '(C) 2013-2014, Alexander Bruy'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'


import os
import re

from PyQt4.QtCore import *

from qgis.core import *

from photo2shape.EXIF import *


class ImportThread(QThread):
    processingFinished = pyqtSignal(list, bool)
    processingInterrupted = pyqtSignal()
    photoProcessed = pyqtSignal()

    def __init__(self, dir, photos, outputFileName, outputEncoding):
        QThread.__init__(self, QThread.currentThread())
        self.baseDir = dir
        self.photos = photos
        self.outputFileName = outputFileName
        self.outputEncoding = outputEncoding

        self.mutex = QMutex()
        self.stopMe = 0
        self.noTags = []

    def run(self):
        self.mutex.lock()
        self.stopMe = 0
        self.mutex.unlock()

        interrupted = False

        shapeFields = QgsFields()
        shapeFields.append(QgsField("filepath", QVariant.String, "", 255))
        shapeFields.append(QgsField("filename", QVariant.String, "", 255))
        shapeFields.append(QgsField("longitude", QVariant.Double))
        shapeFields.append(QgsField("latitude", QVariant.Double))
        shapeFields.append(QgsField("altitude", QVariant.Double))
        shapeFields.append(QgsField("north", QVariant.String, "", 1))
        shapeFields.append(QgsField("direction", QVariant.Double))
        shapeFields.append(QgsField("gps_date", QVariant.String, "", 255))
        shapeFields.append(QgsField("img_date", QVariant.String, "", 255))

        crs = QgsCoordinateReferenceSystem(4326)

        shapeFileWriter = QgsVectorFileWriter(self.outputFileName, self.outputEncoding, shapeFields, QGis.WKBPoint, crs)

        featureId = 0
        for fileName in self.photos:
            path = os.path.abspath(unicode(QFileInfo(self.baseDir + "/" + fileName).absoluteFilePath()))
            photoFile = open(path, "rb")
            exifTags = process_file(photoFile, details=False)
            photoFile.close()

            # check for GPS tags. If no tags found, write message to log and skip this file
            if ("GPS GPSLongitude" not in exifTags) or ("GPS GPSLatitude" not in exifTags):
                self.noTags.append("%s - does not have GPS tags" % (path))
                self.photoProcessed.emit()
                continue

            (lon, lat) = self._getCoordinates(exifTags)
            # if coordinates are empty, write message to log and skip this file
            #if lon == 0 and lat == 0:
            #  self.noTags.append(QString("%1 - has null coordinates").arg(path))
            #  self.emit(SIGNAL("photoProcessed()"))
            #  continue

            altitude = self._getAltitude(exifTags)
            if altitude is None:
                altitude = 0

            imgDirection = self._getDirection(exifTags)
            if imgDirection is None:
                north = ""
                direction = 0
            else:
                north = imgDirection[0]
                direction = imgDirection[1]

            gpsDate = self._getGPSDateTime(exifTags)
            imgDate = self._getImageDateTime(exifTags)

            exifTags = None

            # write point to the shapefile
            feature = QgsFeature()
            feature.initAttributes(shapeFields.count())
            geometry = QgsGeometry()
            point = QgsPoint(lon, lat)
            feature.setGeometry(geometry.fromPoint(point))
            feature.setAttribute(0, path)
            feature.setAttribute(1, fileName)
            feature.setAttribute(2, lon)
            feature.setAttribute(3, lat)
            feature.setAttribute(4, altitude)
            feature.setAttribute(5, north)
            feature.setAttribute(6, direction)
            feature.setAttribute(7, gpsDate)
            feature.setAttribute(8, imgDate)
            shapeFileWriter.addFeature(feature)
            featureId += 1

            self.photoProcessed.emit()

            self.mutex.lock()
            s = self.stopMe
            self.mutex.unlock()
            if s == 1:
                interrupted = True
                break

        del shapeFileWriter
        haveShape = True

        if not interrupted:
            if featureId == 0:
                QgsVectorFileWriter.deleteShapeFile(self.outputFileName)
                haveShape = False
            self.processingFinished.emit(self.noTags, haveShape)
        else:
            self.processingInterrupted.emit()

    def stop(self):
        self.mutex.lock()
        self.stopMe = 1
        self.mutex.unlock()

        QThread.wait(self)

    def _getCoordinates(self, tags):
        exifTags = tags

        # some devices (e.g. with Android 1.6) write tags in non standard way
        # as decimal degrees in ASCII field
        if FIELD_TYPES[exifTags["GPS GPSLongitude"].field_type][2] == 'ASCII':
            strLon = str(exifTags["GPS GPSLongitude"])
            strLat = str(exifTags["GPS GPSLatitude"])
            lon = round(float(strLon), 7)
            lat = round(float(strLat), 7)
            return (lon, lat)

        # get the position info as reported by EXIF
        lonDirection = None
        lonDegrees = None
        lonMinutes = None
        lonSeconds = None
        latDirection = None
        latDegrees = None
        latMinutes = None
        latSeconds = None

        # longitude direction will be either "E" or "W"
        lonDirection = str(exifTags["GPS GPSLongitudeRef"])
        # EXIF returns degrees, minutes and seconds in list, so we need to split it
        longitude = str(exifTags["GPS GPSLongitude"])[1:-1].split(", ")
        lonDegrees = longitude[0]
        lonMinutes = longitude[1]
        lonSeconds = longitude[2]

        # latitude direction will be either "N" or "S"
        latDirection = str(exifTags["GPS GPSLatitudeRef"])
        # EXIF returns degrees, minutes and seconds in list, so we need to split it
        latitude = str(exifTags["GPS GPSLatitude"])[1:-1].split(", ")
        latDegrees = latitude[0]
        latMinutes = latitude[1]
        latSeconds = latitude[2]

        # get the degree, minutes and seconds values
        regexp = re.compile("^[0-9]*")
        lonDegreesFloat = float(regexp.search(str(lonDegrees)).group())
        lonMinutesFloat = float(regexp.search(str(lonMinutes)).group())
        lonSecondsFloat = float(regexp.search(str(lonSeconds)).group())
        latDegreesFloat = float(regexp.search(str(latDegrees)).group())
        latMinutesFloat = float(regexp.search(str(latMinutes)).group())
        latSecondsFloat = float(regexp.search(str(latSeconds)).group())

        # divide the values by the divisor if neccessary
        regexp = re.compile("[0-9]*$")
        if lonDegrees.find("/") == -1:
            myLonDegrees = lonDegreesFloat
        else:
            if lonDegreesFloat != 0.0:
                myLonDegrees = lonDegreesFloat / float(regexp.search(str(lonDegrees)).group())
            else:
                myLonDegrees = 0.0
        if lonMinutes.find("/") == -1:
            myLonMinutes = lonMinutesFloat
        else:
            if lonMinutesFloat != 0.0:
                myLonMinutes = lonMinutesFloat / float(regexp.search(str(lonMinutes)).group())
            else:
                myLonMinutes = 0.0
        if lonSeconds.find("/") == -1:
            myLonSeconds = lonSecondsFloat
        else:
            if lonSecondsFloat != 0.0:
                myLonSeconds = lonSecondsFloat / float(regexp.search(str(lonSeconds)).group())
            else:
                myLonSeconds = 0.0

        if latDegrees.find("/") == -1:
            myLatDegrees = latDegreesFloat
        else:
            if latDegreesFloat != 0.0:
                myLatDegrees = latDegreesFloat / float(regexp.search(str(latDegrees)).group())
            else:
                myLatDegrees = 0.0
        if latMinutes.find("/") == -1:
            myLatMinutes = latMinutesFloat
        else:
            if latMinutesFloat != 0.0:
                myLatMinutes = latMinutesFloat / float(regexp.search(str(latMinutes)).group())
            else:
                myLatMinutes = 0.0
        if latSeconds.find("/") == -1:
            myLatSeconds = latSecondsFloat
        else:
            if latSecondsFloat != 0.0:
                myLatSeconds = latSecondsFloat / float(regexp.search(str(latSeconds)).group())
            else:
                myLatSeconds = 0.0

        # we now have degrees, decimal minutes and decimal seconds, so convert to decimal degrees
        if myLonMinutes != 0.0:
            myLonMinutes = myLonMinutes / 60
        if myLonSeconds != 0.0:
            myLonSeconds = myLonSeconds / 3600
        if myLatMinutes != 0.0:
            myLatMinutes = myLatMinutes / 60
        if myLonSeconds != 0.0:
            myLatSeconds = myLatSeconds / 3600

        lon = round(myLonDegrees + myLonMinutes + myLonSeconds, 7)
        lat = round(myLatDegrees + myLatMinutes + myLatSeconds, 7)

        # use a negative sign as needed
        if lonDirection == "W":
            lon = 0 - lon
        if latDirection == "S":
            lat = 0 - lat

        return (lon, lat)

    def _getAltitude(self, tags):
        exifTags = tags

        if "GPS GPSAltitude" not in exifTags:
            return None

        # some devices (e.g. with Android 1.6) write tags in non standard way
        # as decimal degrees in ASCII field also they don't write
        # GPS GPSAltitudeRef tag
        if FIELD_TYPES[exifTags["GPS GPSAltitude"].field_type][2] == 'ASCII':
            alt = str(exifTags["GPS GPSAltitude"])
            return round(float(alt), 7)

        if "GPS GPSAltitudeRef" not in exifTags:
            return None

        # altitude
        altDirection = exifTags["GPS GPSAltitudeRef"]
        altitude = str(exifTags["GPS GPSAltitude"])

        # get altitude value
        regexp = re.compile("^[0-9]*")
        altitudeFloat = float(regexp.search(str(altitude)).group())

        # divide the value by the divisor if neccessary
        regexp = re.compile("[0-9]*$")
        if altitude.find("/") == -1:
            myAltitude = altitudeFloat
        else:
            if altitudeFloat != 0.0:
                myAltitude = altitudeFloat / float(regexp.search(str(altitude)).group())
            else:
                myAltitude = 0.0

        # use negative sign as needed
        if altDirection == 1:
            myAltitude = 0 - myAltitude

        return round(myAltitude, 7)

    def _getGPSDateTime(self, tags):
        exifTags = tags

        imgDate = None
        imgTime = None

        if "GPS GPSDate" in exifTags:
            imgDate = str(exifTags["GPS GPSDate"])

        if "GPS GPSTimeStamp" in exifTags:
            # some devices (e.g. Android) save this tag in non-standard way
            if FIELD_TYPES[exifTags["GPS GPSTimeStamp"].field_type][2] == 'ASCII':
                return str(exifTags["GPS GPSTimeStamp"])
            else:
                tmp = str(exifTags["GPS GPSTimeStamp"])[1:-1].split(", ")
                imgTime = tmp[0] + ":" + tmp[1] + ":" + tmp[2]
                if imgDate is None:
                    return imgTime
                return imgDate + " " + imgTime

        return None

    def _getImageDateTime(self, tags):
        exifTags = tags

        if "Image DateTime" in exifTags:
            return str(exifTags["Image DateTime"])

        return None

    def _getDirection(self, tags):
        exifTags = tags

        if "GPS GPSImgDirection" not in exifTags:
            return None

        myAzimuth = str(exifTags["GPS GPSImgDirectionRef"])
        direction = str(exifTags["GPS GPSImgDirection"])

        # get direction value
        regexp = re.compile("^[0-9]*")
        directionFloat = float(regexp.search(str(direction)).group())

        # divide the value by the divisor if neccessary
        regexp = re.compile("[0-9]*$")
        if direction.find("/") == -1:
            myDirection = directionFloat
        else:
            myDirection = directionFloat / float(regexp.search(str(direction)).group())

        return (myAzimuth, round(myDirection, 7))
